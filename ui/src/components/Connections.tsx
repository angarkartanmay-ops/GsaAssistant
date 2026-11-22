import { motion } from "framer-motion";
import { ArrowClockwise, ArrowSquareOut, CheckCircle, CircleNotch, Desktop, DeviceMobile, GoogleLogo, LockKey, X } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError, postJson, type SettingsView } from "../lib/api";

type Fields = Record<string, string>;
type Secrets = Record<string, string | null>;

const VOICES = [
  { id: "bf_emma:0.6,bf_isabella:0.4", label: "Blend (default)" },
  { id: "bf_emma", label: "Emma" },
  { id: "bf_isabella", label: "Isabella" },
  { id: "bf_alice", label: "Alice" },
  { id: "bf_lily", label: "Lily" },
];
const SASS = ["None", "Light", "Regular", "Full sass"];

const VALIDATE: Record<string, (v: string) => string | null> = {
  "gmail.address": (v) => (!v || /^\S+@\S+\.\S+$/.test(v) ? null : "That isn't an email address."),
  "gmail.official_address": (v) => (!v || /^\S+@\S+\.\S+$/.test(v) ? null : "That isn't an email address."),
  "discord.guild_id": (v) => (!v || /^\d{15,22}$/.test(v) ? null : "Server IDs are 17-20 digits (right-click the server > Copy Server ID)."),
  "discord.owner_user_id": (v) => (!v || /^\d{15,22}$/.test(v) ? null : "User IDs are 17-20 digits (right-click yourself > Copy User ID)."),
  "dashboard.url": (v) => (!v || /^https?:\/\//.test(v) ? null : "Start with https://"),
};
const VALIDATE_SECRET: Record<string, (v: string) => string | null> = {
  "server.pin": (v) => (/^\d{4,12}$/.test(v) ? null : "4 to 12 digits."),
  "gmail.app_password": (v) => (/^[a-zA-Z ]{16,19}$/.test(v) ? null : "App Passwords are 16 letters."),
  "gmail.official_app_password": (v) => (/^[a-zA-Z ]{16,19}$/.test(v) ? null : "App Passwords are 16 letters."),
};

function Field({ id, label, hint, value, onChange, placeholder, error }: {
  id: string; label: string; hint?: React.ReactNode; value: string; onChange: (v: string) => void; placeholder?: string; error?: string | null;
}) {
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-[13px] font-medium text-fog-300">{label}</label>
      <input id={id} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="field" autoComplete="off" spellCheck={false} />
      {error ? <p className="text-[12.5px] text-bad">{error}</p> : hint && <p className="text-[12.5px] leading-relaxed text-fog-500">{hint}</p>}
    </div>
  );
}

function TextArea({ id, label, hint, value, onChange, placeholder }: {
  id: string; label: string; hint?: React.ReactNode; value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-[13px] font-medium text-fog-300">{label}</label>
      <textarea id={id} value={value} rows={3} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="field resize-y leading-6" />
      {hint && <p className="text-[12.5px] leading-relaxed text-fog-500">{hint}</p>}
    </div>
  );
}

function SecretField({ id, label, hint, isSet, value, onChange, error }: {
  id: string; label: string; hint?: React.ReactNode; isSet: boolean; value: string | null | undefined; onChange: (v: string | null) => void; error?: string | null;
}) {
  const cleared = value === null;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <label htmlFor={id} className="flex items-center gap-1.5 text-[13px] font-medium text-fog-300">
          <LockKey size={13} /> {label}
        </label>
        {isSet && !cleared && !value && (
          <span className="inline-flex items-center gap-1 font-mono text-[11px] uppercase tracking-[0.12em] text-ok">
            <CheckCircle size={12} weight="fill" /> saved
            <button onClick={() => onChange(null)} className="ml-1 rounded px-1 text-fog-500 hover:text-bad">clear</button>
          </span>
        )}
        {cleared && <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-warn">will be removed</span>}
      </div>
      <input
        id={id}
        type="password"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder={isSet ? "Paste to replace" : "Paste here"}
        className="field font-mono"
        autoComplete="new-password"
      />
      {error ? <p className="text-[12.5px] text-bad">{error}</p> : hint && <p className="text-[12.5px] leading-relaxed text-fog-500">{hint}</p>}
    </div>
  );
}

function Group({ title, intro, children }: { title: string; intro?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="grid gap-5 border-t border-white/[0.06] py-7 md:grid-cols-[200px_minmax(0,1fr)] md:gap-10">
      <div>
        <h3 className="text-[15px] font-semibold tracking-tight text-fog-100">{title}</h3>
        {intro && <p className="mt-1.5 text-[13px] leading-relaxed text-fog-500">{intro}</p>}
      </div>
      <div className="grid gap-5 sm:grid-cols-2">{children}</div>
    </section>
  );
}

function Segmented({ options, value, onChange, label }: { options: { id: string; label: string }[]; value: string; onChange: (v: string) => void; label: string }) {
  return (
    <div className="flex flex-col gap-2 sm:col-span-2">
      <span className="text-[13px] font-medium text-fog-300">{label}</span>
      <div className="inline-flex flex-wrap gap-1 self-start rounded-xl bg-ink-850 p-1">
        {options.map((o) => (
          <button
            key={o.id}
            onClick={() => onChange(o.id)}
            className={`tactile relative rounded-lg px-3 py-1.5 text-[13px] ${value === o.id ? "text-ink-950" : "text-fog-300 hover:text-fog-100"}`}
          >
            {value === o.id && <motion.span layoutId={`seg-${label}`} className="absolute inset-0 rounded-lg bg-signal" transition={{ type: "spring", stiffness: 300, damping: 30 }} />}
            <span className="relative">{o.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function WhatsAppLink() {
  const [qr, setQr] = useState<{ dataUrl?: string | null; connected?: boolean; error?: string } | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => api<{ dataUrl: string | null; connected?: boolean }>("/api/whatsapp/qr").then((q) => alive && setQr(q)).catch((e) => alive && setQr({ error: (e as Error).message }));
    load();
    const t = window.setInterval(load, 5000);
    return () => ((alive = false), window.clearInterval(t));
  }, []);
  if (!qr) return <div className="skeleton h-40 w-40 rounded-xl" />;
  if (qr.error) return <p className="text-[13px] text-fog-500">The WhatsApp bridge isn't running yet. It starts with HAVOC; this updates on its own.</p>;
  if (qr.dataUrl) return (
    <div className="flex items-start gap-4">
      <img src={qr.dataUrl} alt="WhatsApp link code" className="h-40 w-40 rounded-xl bg-white p-2" />
      <p className="max-w-[30ch] text-[13px] leading-relaxed text-fog-500">On your phone: WhatsApp, Settings, Linked devices, Link a device. Scan this.</p>
    </div>
  );
  return <p className="flex items-center gap-1.5 text-[13.5px] text-ok"><CheckCircle size={15} weight="fill" /> Linked. Your WhatsApp is connected.</p>;
}

export function Connections({ onClose }: { onClose: () => void }) {
  const [view, setView] = useState<SettingsView | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [fields, setFields] = useState<Fields>({});
  const [secrets, setSecrets] = useState<Secrets>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    api<SettingsView>("/api/settings")
      .then((v) => {
        setView(v);
        const f: Fields = {};
        Object.entries(v.fields).forEach(([k, val]) => (f[k] = Array.isArray(val) ? val.join(", ") : val == null || val === 0 ? "" : String(val)));
        setFields(f);
      })
      .catch((e) => setLoadError(e instanceof ApiError && e.status === 403 ? "pc-only" : (e as Error).message));
  }, []);

  const set = (k: string) => (v: string) => (setFields((f) => ({ ...f, [k]: v })), setSaved(false));
  const setSecret = (k: string) => (v: string | null) => (setSecrets((s) => ({ ...s, [k]: v })), setSaved(false));
  const errors = useMemo(() => {
    const e: Record<string, string | null> = {};
    Object.entries(VALIDATE).forEach(([k, fn]) => (e[k] = fn(fields[k] ?? "")));
    Object.entries(VALIDATE_SECRET).forEach(([k, fn]) => (e[k] = secrets[k] ? fn(secrets[k] as string) : null));
    return e;
  }, [fields, secrets]);
  const hasErrors = Object.values(errors).some(Boolean);

  const dirtyFields = () => {
    const out: Record<string, string> = {};
    if (!view) return out;
    Object.entries(fields).forEach(([k, v]) => {
      const orig = view.fields[k];
      const o = Array.isArray(orig) ? orig.join(", ") : orig == null || orig === 0 ? "" : String(orig);
      if (o !== v) out[k] = v;
    });
    return out;
  };

  const save = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const payload = { fields: dirtyFields(), secrets: Object.fromEntries(Object.entries(secrets).filter(([, v]) => v === null || (v && v.trim()))) };
      await postJson("/api/settings", payload);
      setSaved(true);
      setSecrets({});
      setView(await api<SettingsView>("/api/settings"));
    } catch (e) {
      setSaveError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const restart = async () => {
    setRestarting(true);
    try {
      await postJson("/api/restart", {});
    } catch (e) {
      setSaveError((e as Error).message);
      setRestarting(false);
      return;
    }
    const started = Date.now();
    const poll = async () => {
      try {
        await api("/api/me");
        if (Date.now() - started > 2500) return window.location.reload();
      } catch { /* still restarting */ }
      window.setTimeout(poll, 1200);
    };
    window.setTimeout(poll, 2500);
  };

  const connect = async (what: "dashboard" | "mail" | "phone") => {
    setNotice(null);
    try {
      const r = await postJson<{ message: string }>(`/api/connect/${what}`, {});
      setNotice(r.message);
    } catch (e) {
      setNotice((e as Error).message);
    }
  };

  const f = (k: string) => fields[k] ?? "";
  const s = view?.secrets ?? {};

  return (
    <motion.div className="fixed inset-0 z-30 flex justify-end" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-ink-950/70 backdrop-blur-sm" onClick={onClose} />
      <motion.div
        role="dialog"
        aria-label="Connections"
        initial={{ x: 40, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        exit={{ x: 40, opacity: 0 }}
        transition={{ type: "spring", stiffness: 140, damping: 22 }}
        className="relative flex h-[100dvh] w-full max-w-[920px] flex-col border-l border-white/[0.06] bg-ink-900"
      >
        <header className="flex items-start justify-between gap-4 px-6 pb-4 pt-6 sm:px-10">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">Connections</h2>
            <p className="mt-1 max-w-[56ch] text-[13.5px] leading-relaxed text-fog-500">
              Everything here is saved on this PC only. Passwords and tokens are written to <code className="font-mono text-fog-300">.env</code> and never shown again, not even to you.
            </p>
          </div>
          <button aria-label="Close" onClick={onClose} className="tactile rounded-xl p-2 text-fog-500 hover:bg-ink-800 hover:text-fog-100">
            <X size={18} weight="bold" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 sm:px-10">
          {loadError === "pc-only" ? (
            <div className="flex max-w-[48ch] items-start gap-3 py-10 text-fog-300">
              <Desktop size={22} className="mt-0.5 shrink-0 text-signal" />
              <p className="leading-relaxed">Connections can only be changed on the PC itself, so nobody with your phone can read or swap your keys. Open HAVOC on the PC to edit them.</p>
            </div>
          ) : loadError ? (
            <p className="py-10 text-bad">Couldn't load settings: {loadError}</p>
          ) : !view ? (
            <div className="space-y-6 py-8">{[1, 2, 3].map((i) => <div key={i} className="skeleton h-28 rounded-2xl" />)}</div>
          ) : (
            <>
              <Group title="You" intro="How HAVOC talks to you.">
                <Field id="name" label="Your first name" value={f("assistant.user_name")} onChange={set("assistant.user_name")} />
                <Field id="address" label="What it calls you" value={f("assistant.address_as")} onChange={set("assistant.address_as")} />
                <Segmented label="Sarcasm" value={f("assistant.sass") || "0"} onChange={set("assistant.sass")} options={SASS.map((l, i) => ({ id: String(i), label: l }))} />
                <Segmented label="Voice" value={f("voice.tts_voice")} onChange={set("voice.tts_voice")} options={VOICES} />
              </Group>

              <Group
                title="Mail"
                intro={<>Reads the inbox that gets GSA mail; sends from your official address. App Passwords need 2-Step Verification: <a className="text-signal underline-offset-2 hover:underline" href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer">create one</a>.</>}
              >
                <Field id="gmail" label="Inbox address (reads)" value={f("gmail.address")} onChange={set("gmail.address")} placeholder="you@gmail.com" error={errors["gmail.address"]} />
                <SecretField id="gmailpw" label="Inbox App Password" isSet={!!s["gmail.app_password"]} value={secrets["gmail.app_password"]} onChange={setSecret("gmail.app_password")} error={errors["gmail.app_password"]} />
                <Field id="official" label="Official address (sends)" value={f("gmail.official_address")} onChange={set("gmail.official_address")} placeholder="Leave empty to send from the inbox" error={errors["gmail.official_address"]} />
                <Field id="sender" label="Name on sent mail" value={f("gmail.sender_name")} onChange={set("gmail.sender_name")} placeholder="Tanmay ..." />
                <Segmented
                  label="Sending"
                  value={f("gmail.send_mode") || "smtp"}
                  onChange={set("gmail.send_mode")}
                  options={[{ id: "draft", label: "Open as Gmail draft" }, { id: "smtp", label: "Send directly" }]}
                />
                <TextArea id="sig" label="Signature" value={f("gmail.signature")} onChange={set("gmail.signature")} placeholder={"Tanmay Angarkar\nGoogle Student Ambassador"} hint="Added to the end of every email HAVOC writes." />
                {f("gmail.send_mode") === "draft" ? (
                  <p className="self-end text-[12.5px] leading-relaxed text-fog-500">
                    HAVOC writes the email and opens it ready to send in {f("gmail.official_address") || f("gmail.address") || "your Gmail"}. You press Send. No password needed for the sending account.
                  </p>
                ) : (
                  f("gmail.official_address") && (
                    <>
                      <Segmented label="Official account sign-in" value={f("gmail.official_auth") || "app_password"} onChange={set("gmail.official_auth")} options={[{ id: "app_password", label: "App Password" }, { id: "oauth", label: "Sign in with Google" }]} />
                      {f("gmail.official_auth") === "oauth" ? (
                        <div className="flex flex-col gap-2 sm:col-span-2">
                          <p className="text-[12.5px] leading-relaxed text-fog-500">
                            {view.oauth_client_present ? "OAuth client found." : "First put your OAuth client JSON at data/google_oauth_client.json (README, Mail section)."} Save, then:
                          </p>
                          <button onClick={() => connect("mail")} className="tactile inline-flex items-center gap-2 self-start rounded-xl border border-white/[0.08] px-3.5 py-2 text-[13.5px] hover:bg-ink-800">
                            <GoogleLogo size={16} weight="bold" /> Sign in with Google
                          </button>
                        </div>
                      ) : (
                        <SecretField id="offpw" label="Official App Password" isSet={!!s["gmail.official_app_password"]} value={secrets["gmail.official_app_password"]} onChange={setSecret("gmail.official_app_password")} error={errors["gmail.official_app_password"]} />
                      )}
                    </>
                  )
                )}
              </Group>

              <Group title="GSA dashboard" intro="The ambassador web app with your tasks. Sign in once; the session stays on this PC.">
                <Field id="dash" label="Dashboard URL" value={f("dashboard.url")} onChange={set("dashboard.url")} placeholder="https://..." error={errors["dashboard.url"]} />
                <div className="flex items-end">
                  <button onClick={() => connect("dashboard")} disabled={!view.fields["dashboard.url"]} className="tactile inline-flex items-center gap-2 rounded-xl border border-white/[0.08] px-3.5 py-2.5 text-[13.5px] hover:bg-ink-800 disabled:opacity-40">
                    <ArrowSquareOut size={16} /> Sign in on this PC
                  </button>
                </div>
              </Group>

              <Group
                title="Discord"
                intro={<>Make a bot at <a className="text-signal underline-offset-2 hover:underline" href="https://discord.com/developers/applications" target="_blank" rel="noreferrer">discord.com/developers</a>, turn on Message Content Intent, paste its token. Turn on Developer Mode to copy IDs.</>}
              >
                <SecretField id="dtok" label="Bot token" isSet={!!s["discord.token"]} value={secrets["discord.token"]} onChange={setSecret("discord.token")} />
                <Field id="guild" label="Server ID" value={f("discord.guild_id")} onChange={set("discord.guild_id")} error={errors["discord.guild_id"]} />
                <Field id="ownername" label="Your username" value={f("discord.owner_username")} onChange={set("discord.owner_username")} placeholder="tanmay_7697" hint="Your DMs to the bot become commands. HAVOC locks onto your account on your first DM." />
                <Field id="owner" label="Your user ID (optional)" value={f("discord.owner_user_id")} onChange={set("discord.owner_user_id")} error={errors["discord.owner_user_id"]} />
                <Field id="chan" label="Default channel" value={f("discord.default_channel")} onChange={set("discord.default_channel")} placeholder="general" hint="A name, a channel ID, or a channel link." />
                <Field id="postas" label="Name on posts" value={f("discord.post_as_name")} onChange={set("discord.post_as_name")} hint="Posts show this name and your avatar." />
                {view.discord_invite_url && (
                  <div className="flex items-end">
                    <a href={view.discord_invite_url} target="_blank" rel="noreferrer" className="tactile inline-flex items-center gap-2 rounded-xl border border-white/[0.08] px-3.5 py-2.5 text-[13.5px] hover:bg-ink-800">
                      <ArrowSquareOut size={16} /> Invite the bot to your server
                    </a>
                  </div>
                )}
              </Group>

              <Group title="WhatsApp" intro="Links as a device, like WhatsApp Web. Unofficial: keep sending human-sized.">
                <Field id="wag" label="GSA group name" value={f("whatsapp.group_name")} onChange={set("whatsapp.group_name")} hint="Part of the name is enough." />
                <div className="sm:col-span-2"><WhatsAppLink /></div>
              </Group>

              <Group title="Phone" intro="Your phone reaches this PC through Tailscale; the PIN locks it if the phone is lost.">
                <SecretField id="pin" label="Phone PIN" isSet={!!s["server.pin"]} value={secrets["server.pin"]} onChange={setSecret("server.pin")} error={errors["server.pin"]} />
                <Field id="hosts" label="This PC's Tailscale name" value={f("server.remote_hosts")} onChange={set("server.remote_hosts")} placeholder="my-pc.tail1234.ts.net" hint={view.phone_url ? <>Phone address: <span className="font-mono text-fog-300">{view.phone_url}</span></> : "Filled in by the button below."} />
                <div className="flex flex-col gap-2 sm:col-span-2">
                  <button onClick={() => connect("phone")} className="tactile inline-flex items-center gap-2 self-start rounded-xl border border-white/[0.08] px-3.5 py-2.5 text-[13.5px] hover:bg-ink-800">
                    <DeviceMobile size={16} /> Set up phone access
                  </button>
                  <p className="text-[12.5px] leading-relaxed text-fog-500">Signs this PC in to Tailscale (free) and publishes HAVOC privately. Then install Tailscale and the HAVOC app on your phone with the same account. The result shows up under Alerts.</p>
                </div>
              </Group>
              <div className="h-6" />
            </>
          )}
        </div>

        {view && (
          <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] px-6 py-4 sm:px-10">
            <div className="min-h-5 text-[13px]">
              {saveError ? <span className="text-bad">{saveError}</span> : notice ? <span className="text-fog-300">{notice}</span> : saved ? <span className="text-ok">Saved. Restart HAVOC to apply.</span> : hasErrors ? <span className="text-warn">Fix the highlighted fields first.</span> : null}
            </div>
            <div className="flex gap-2">
              {saved && (
                <button onClick={restart} disabled={restarting} className="tactile inline-flex items-center gap-2 rounded-xl border border-white/[0.08] px-4 py-2.5 text-sm hover:bg-ink-800 disabled:opacity-60">
                  {restarting ? <CircleNotch size={16} className="animate-spin" /> : <ArrowClockwise size={16} />} {restarting ? "Restarting" : "Restart now"}
                </button>
              )}
              <button onClick={save} disabled={saving || hasErrors} className="tactile inline-flex items-center gap-2 rounded-xl bg-signal px-5 py-2.5 text-sm font-semibold text-ink-950 hover:bg-signal-strong disabled:opacity-50">
                {saving && <CircleNotch size={16} className="animate-spin" />} Save
              </button>
            </div>
          </footer>
        )}
      </motion.div>
    </motion.div>
  );
}
