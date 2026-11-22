"""Gmail over IMAP/SMTP, with an App Password (no Google Cloud project) or OAuth.

Search uses Gmail's own query syntax via the X-GM-RAW IMAP extension, so the GSA filter
in config.yaml is written exactly like the Gmail search box.
"""
from __future__ import annotations

import base64
import email
import email.utils
import html
import imaplib
import mimetypes
import re
import smtplib
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.policy import default as default_policy
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlencode

from ..config import GmailCfg


@dataclass
class Mail:
    uid: str
    msgid: str
    thread_id: str
    sender: str
    to: str
    subject: str
    date: str
    body: str
    message_id: str = ""
    references: str = ""
    unread: bool = False
    labels: list[str] = field(default_factory=list)

    def short(self, body_chars: int = 600) -> str:
        flag = " (unread)" if self.unread else ""
        body = re.sub(r"\s+", " ", self.body)[:body_chars]
        return f"[id {self.msgid}]{flag} {self.date} | From: {self.sender} | Subject: {self.subject}\n{body}"


class GmailError(RuntimeError):
    pass


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(raw)
    return re.sub(r"[ \t ]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()


def extract_body(msg: email.message.EmailMessage) -> str:
    plain = msg.get_body(preferencelist=("plain",))
    if plain is not None:
        try:
            return _strip_quoted(plain.get_content())
        except (LookupError, UnicodeDecodeError):
            pass
    rich = msg.get_body(preferencelist=("html",))
    if rich is not None:
        try:
            return _strip_quoted(html_to_text(rich.get_content()))
        except (LookupError, UnicodeDecodeError):
            pass
    return ""


def _strip_quoted(text: str) -> str:
    """Drop the quoted history of a reply chain ("On ... wrote:")."""
    m = re.search(r"\n\s*On .{5,120}wrote:\s*\n", text)
    if m:
        text = text[:m.start()]
    return "\n".join(l for l in text.splitlines() if not l.startswith(">")).strip()


def parse_fetch(data: list) -> list[Mail]:
    """Parse imaplib UID FETCH output into Mail objects."""
    mails: list[Mail] = []
    for item in data:
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        meta = item[0].decode(errors="ignore")
        raw = item[1]
        uid = _re1(r"UID (\d+)", meta)
        msgid = _re1(r"X-GM-MSGID (\d+)", meta) or uid
        thrid = _re1(r"X-GM-THRID (\d+)", meta) or msgid
        flags = _re1(r"FLAGS \(([^)]*)\)", meta) or ""
        labels = re.findall(r'"([^"]+)"|(\\\w+)', _re1(r"X-GM-LABELS \(([^)]*)\)", meta) or "")
        msg = email.message_from_bytes(raw, policy=default_policy)
        mails.append(Mail(
            uid=uid, msgid=msgid, thread_id=thrid,
            sender=str(msg.get("From", "")), to=str(msg.get("To", "")),
            subject=str(msg.get("Subject", "(no subject)")),
            date=_fmt_date(str(msg.get("Date", ""))),
            body=extract_body(msg)[:6000],
            message_id=str(msg.get("Message-ID", "")), references=str(msg.get("References", "")),
            unread="\\Seen" not in flags,
            labels=[a or b for a, b in labels],
        ))
    return mails


def _re1(pat: str, s: str) -> Optional[str]:
    m = re.search(pat, s)
    return m.group(1) if m else None


def _fmt_date(d: str) -> str:
    try:
        dt = email.utils.parsedate_to_datetime(d)
        return dt.astimezone().strftime("%a %d %b %H:%M")
    except (TypeError, ValueError):
        return d


@dataclass
class Account:
    address: str
    secret: str  # App Password; unused for oauth
    auth: str  # "app_password" | "oauth"

    @property
    def usable(self) -> bool:
        return bool(self.address and (self.secret or self.auth == "oauth"))


class GmailClient:
    def __init__(self, cfg: GmailCfg):
        self.cfg = cfg
        self.cache: dict[str, Mail] = {}

    @property
    def reader(self) -> Account:
        return Account(self.cfg.address, self.cfg.app_password, self.cfg.auth)

    @property
    def sender(self) -> Account:
        """Outgoing mail goes from the official account when one is set."""
        if self.cfg.official_address:
            return Account(self.cfg.official_address, self.cfg.official_app_password, self.cfg.official_auth)
        return self.reader

    @property
    def configured(self) -> bool:
        return bool(self.cfg.enabled and self.reader.usable)

    @property
    def can_send(self) -> bool:
        return bool(self.cfg.enabled and self.sender.usable)

    def _xoauth2(self, acct: Account) -> str:
        from .google_oauth import access_token
        token = access_token(acct.address, self.cfg.oauth_client_file)
        return f"user={acct.address}\x01auth=Bearer {token}\x01\x01"

    def _imap(self, acct: Optional[Account] = None) -> imaplib.IMAP4_SSL:
        acct = acct or self.reader
        if not (self.cfg.enabled and acct.usable):
            raise GmailError("Gmail isn't set up. Put GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env "
                             "(App Password: myaccount.google.com/apppasswords), or use gmail.auth: oauth.")
        M = imaplib.IMAP4_SSL(self.cfg.imap_host)
        try:
            if acct.auth == "oauth":
                auth = self._xoauth2(acct).encode()
                M.authenticate("XOAUTH2", lambda _: auth)
            else:
                M.login(acct.address, acct.secret)
        except imaplib.IMAP4.error as e:
            raise GmailError(f"Login to {acct.address} failed: {e}. Check the App Password and that IMAP "
                             "is on (or run `python -m havoc login-mail` for oauth).") from e
        return M

    def search(self, query: str, limit: int = 25) -> list[Mail]:
        M = self._imap()
        try:
            M.select(self.cfg.mailbox, readonly=True)
            M.literal = query.encode("utf-8")
            typ, data = M.uid("SEARCH", "CHARSET", "UTF-8", "X-GM-RAW")
            if typ != "OK":
                raise GmailError(f"search failed: {data}")
            uids = data[0].split()[-limit:]
            if not uids:
                return []
            typ, fetched = M.uid("FETCH", b",".join(uids),
                                 "(UID FLAGS X-GM-MSGID X-GM-THRID X-GM-LABELS BODY.PEEK[])")
            mails = parse_fetch(fetched)
            mails.sort(key=lambda m: int(m.uid), reverse=True)
            self.cache.update({m.msgid: m for m in mails})
            return mails
        finally:
            _close(M)

    def gsa_mails(self, days: int = 7, unread_only: bool = False, limit: Optional[int] = None) -> list[Mail]:
        q = f"{self.cfg.gsa_query} newer_than:{max(1, days)}d"
        if unread_only:
            q += " is:unread"
        return self.search(q, limit or self.cfg.max_results)

    def get(self, msgid: str) -> Optional[Mail]:
        msgid = msgid.strip()
        if msgid in self.cache:
            return self.cache[msgid]
        if not msgid.isdigit():
            res = self.search(f"rfc822msgid:{msgid}", 1)
            return res[0] if res else None
        M = self._imap()
        try:
            M.select(self.cfg.mailbox, readonly=True)
            typ, data = M.uid("SEARCH", "X-GM-MSGID", msgid)
            uids = data[0].split() if typ == "OK" and data and data[0] else []
            if not uids:
                return None
            typ, fetched = M.uid("FETCH", uids[-1],
                                 "(UID FLAGS X-GM-MSGID X-GM-THRID X-GM-LABELS BODY.PEEK[])")
            res = parse_fetch(fetched)
            return res[0] if res else None
        finally:
            _close(M)

    def _from(self) -> str:
        return email.utils.formataddr((self.cfg.sender_name, self.sender.address)) if self.cfg.sender_name \
            else self.sender.address

    def build_reply(self, original: Mail, body: str, attachments: Optional[list[Path]] = None) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self._from()
        msg["To"] = email.utils.parseaddr(original.sender)[1] or original.sender
        subj = original.subject
        msg["Subject"] = subj if subj.lower().startswith("re:") else f"Re: {subj}"
        if original.message_id:
            msg["In-Reply-To"] = original.message_id
            msg["References"] = (original.references + " " + original.message_id).strip()
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg.set_content(body)
        _attach(msg, attachments)
        return msg

    def compose_url(self, to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> str:
        """A Gmail link that opens a ready-to-send draft in the sending account. No login needed
        by HAVOC: you're already signed in to Gmail, you just press Send."""
        params = {"view": "cm", "fs": "1", "to": to, "su": subject, "body": body}
        if cc:
            params["cc"] = cc
        if bcc:
            params["bcc"] = bcc
        account = quote(self.sender.address or "0")
        return f"https://mail.google.com/mail/?authuser={account}&" + urlencode(params, quote_via=quote)

    def build_new(self, to: str, subject: str, body: str,
                  attachments: Optional[list[Path]] = None, cc: str = "", bcc: str = "") -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self._from()
        msg["To"] = to
        if cc:
            msg["Cc"] = cc
        if bcc:
            msg["Bcc"] = bcc  # smtplib.send_message delivers to Bcc and strips the header
        msg["Subject"] = subject
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg.set_content(body)
        _attach(msg, attachments)
        return msg

    def save_draft(self, msg: EmailMessage) -> None:
        """APPEND to Gmail's Drafts folder: it shows up as a real draft in Gmail."""
        M = self._imap()
        try:
            M.append('"[Gmail]/Drafts"', "\\Draft", imaplib.Time2Internaldate(time.time()),
                     msg.as_bytes())
        finally:
            _close(M)

    def send(self, msg: EmailMessage) -> None:
        acct = self.sender
        if not (self.cfg.enabled and acct.usable):
            raise GmailError("No sending account is set up (OFFICIAL_MAIL_* or GMAIL_* in .env).")
        with smtplib.SMTP_SSL(self.cfg.smtp_host, 465, timeout=30) as s:
            if acct.auth == "oauth":
                s.ehlo()
                code, resp = s.docmd("AUTH", "XOAUTH2 " + base64.b64encode(self._xoauth2(acct).encode()).decode())
                if code != 235:
                    raise GmailError(f"SMTP OAuth login failed for {acct.address}: {resp!r}")
            else:
                s.login(acct.address, acct.secret)
            s.send_message(msg)

    def check_login(self) -> str:
        _close(self._imap())
        if self.cfg.official_address:
            _close(self._imap(self.sender))
        return "ok"


def _attach(msg: EmailMessage, files: Optional[list[Path]]) -> None:
    for f in files or []:
        ctype, _ = mimetypes.guess_type(f.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(f.read_bytes(), maintype=maintype, subtype=subtype, filename=_display_name(f))


def _display_name(f: Path) -> str:
    """Inbox files are stored as <timestamp>_<original name>; send them under the original name."""
    return re.sub(r"^\d{10,}_", "", f.name)


def _close(M: imaplib.IMAP4_SSL) -> None:
    try:
        M.logout()
    except Exception:  # noqa: BLE001
        pass
