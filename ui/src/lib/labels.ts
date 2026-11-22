// Human wording for what HAVOC is doing right now.
const TOOL_LABELS: Record<string, string> = {
  gsa_mail_digest: "Reading your GSA mail",
  search_mail: "Searching mail",
  read_mail: "Opening a mail",
  draft_reply: "Drafting a reply",
  send_reply: "Sending the reply",
  send_email: "Sending email",
  dashboard_tasks: "Checking the dashboard",
  dashboard_page: "Reading the dashboard",
  add_task: "Adding a task",
  list_tasks: "Listing tasks",
  complete_task: "Ticking a task off",
  discord_channels: "Listing Discord channels",
  discord_read: "Reading Discord",
  discord_post: "Posting to Discord",
  wa_groups: "Listing WhatsApp groups",
  wa_read: "Reading the WhatsApp group",
  wa_send: "Sending on WhatsApp",
  undo_last_post: "Taking the last post back",
  remember: "Remembering that",
  forget: "Forgetting that",
  remind_me: "Setting a reminder",
  list_reminders: "Checking reminders",
  daily_briefing: "Putting your briefing together",
  web_search: "Searching the web",
  read_webpage: "Reading a page",
  open_app: "Opening an app",
  open_url: "Opening a link",
  list_dir: "Looking in a folder",
  read_file: "Reading a file",
  write_file: "Writing a file",
  run_powershell: "Running a command",
  system_status: "Checking the PC",
  media_control: "Controlling media",
  power_action: "Power action",
  clipboard: "Using the clipboard",
};

export const toolLabel = (name: string) => TOOL_LABELS[name] || name.replace(/_/g, " ");

export const STATE_LABELS: Record<string, string> = {
  offline: "Offline",
  idle: "Standing by",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
};

export const CHANNEL_LABELS: Record<string, string> = {
  text: "PC",
  voice: "Voice",
  phone: "Phone",
  "phone-voice": "Phone voice",
  "discord-dm": "Discord DM",
};
