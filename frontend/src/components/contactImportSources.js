// Shared by the source chooser and the import page so each choice opens its guide.
export const SOURCES = [
  { key: "apple", label: "Apple Contacts", detail: "iPhone, Mac or iCloud", group: "Contacts & spreadsheets", file: ".vcf", steps: "iPhone: Contacts → Lists → touch and hold a list → Export, then save to Files. Mac: Contacts → select contacts → File → Export → Export vCard. iCloud.com: Contacts → select contacts → ⋯ → Export vCard." },
  { key: "google", label: "Google Contacts", detail: "Connect Google or upload an export", group: "Contacts & spreadsheets", file: ".csv or .vcf", steps: "Connect Google below to import directly, or export Google CSV or vCard from contacts.google.com and upload it here." },
  { key: "whatsapp", label: "WhatsApp contacts", detail: "From your phone's address book", group: "Contacts & spreadsheets", file: ".vcf", steps: "WhatsApp uses your phone's address book and has no contact export of its own. Export your phone contacts as a vCard (.vcf), or share one contact card from WhatsApp as a .vcf. Chats and messages are never imported." },
  { key: "android", label: "Android Contacts", detail: "Upload a vCard contact export", group: "Contacts & spreadsheets", file: ".vcf", steps: "In your phone's Contacts app, open Settings → Export and save a .vcf file. Menu names vary by phone. Upload that contact file here." },
  { key: "outlook", label: "Outlook / Microsoft People", detail: "Upload your contact export", group: "Contacts & spreadsheets", file: ".csv or .vcf", steps: "Outlook.com: People → Manage contacts → Export contacts. Outlook desktop: File → Open & Export → Import/Export → Export to a file → CSV." },
  { key: "sheets", label: "Google Sheets", detail: "Download your sheet as CSV", group: "Contacts & spreadsheets", file: ".csv", steps: "Open the tab containing your contacts, then File → Download → Comma-separated values (.csv). Put column names in the first row. Each contact needs an email or a phone number." },
  { key: "excel", label: "Microsoft Excel", detail: "Save your workbook as CSV", group: "Contacts & spreadsheets", file: ".csv", steps: "Open the worksheet containing your contacts, then File → Save As → CSV UTF-8 (.csv). Put column names in the first row. Each contact needs an email or a phone number. Upload the CSV, not the .xlsx workbook." },
  { key: "hubspot", label: "HubSpot", detail: "Upload a contact CSV export", group: "CRMs", file: ".csv", steps: "Contacts → choose a view → Export → CSV." },
  { key: "salesforce", label: "Salesforce", detail: "Upload a contact report as CSV", group: "CRMs", file: ".csv", steps: "Run a Contacts report → Export → Details only → CSV. Admins can also use Data Export." },
  { key: "pipedrive", label: "Pipedrive", detail: "Upload your People export", group: "CRMs", file: ".csv", steps: "Contacts → People → ⋯ → Export filter results → CSV." },
  { key: "zoho", label: "Zoho CRM", detail: "Upload a contact CSV export", group: "CRMs", file: ".csv", steps: "Setup → Data Administration → Export → Contacts → CSV." },
  { key: "other", label: "Another service or file", detail: "Any CSV spreadsheet or vCard", group: "Other", file: ".csv or .vcf", steps: "Export contacts from your service as CSV or vCard (.vcf). For a spreadsheet, save as CSV with column names in the first row. Each contact needs an email or a phone number." },
];

export function importSourcePath(source) {
  return SOURCES.some(item => item.key === source)
    ? `/app/import?source=${encodeURIComponent(source)}`
    : "/app/import";
}
