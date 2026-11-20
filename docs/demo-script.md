# Demo script

Three scenes, about four minutes. There are no ready-made examples: type or paste your own
text. The stack needs an OpenAI API key in `.env` and starts empty.

Open http://localhost:8080. The role switcher is at the top right, labelled **Demo
sign-in**: Employee and Admin.

## Before you start

| Check | How |
| --- | --- |
| The stack is up | `docker compose up --build -d`, then the page loads |
| Injection protection is at Standard | As Admin, **Configure**, under **Policy**: **Agent injection protection** shows **Standard** |
| No email has gone outside | Sent emails: "Nothing has been sent"; otherwise **Clear** |

To start again from nothing: `docker compose down -v`, then `docker compose up --build -d`.

## Scene 1: Employee

*An employee sends sensitive text to an AI tool.*

1. Switch to **Employee**. You are on **Chat**.
2. The button at the bottom left of the message box names the AI tool the message goes
   to. Click it: Approved Tool, Tolerated Tool, Unapproved Tool, each with a dot in its
   colour.
3. Choose **Unapproved Tool**, type a message with a name, a tax number, an IBAN, a
   password or a student number, and press **Enter**. For example:
   `Ο κωδικός μου είναι Maria1990! και το ΑΦΜ του πελάτη μου είναι 094014201`
4. Read the exchange from the top:
   - **Your message**, with the sensitive values highlighted.
   - **The line under it** says what the firewall did, for example "2 values masked".
     Beside it, switch from **You** to **Unapproved Tool**: the message now shows what
     the tool saw, with placeholders such as `<PASSWORD_1>` and `<AFM_1>` in place.
   - **The answer**, with the real values restored.
5. Paste an API key and send it. The line says "Blocked"; **Send with placeholders
   anyway** sends it with the key removed.
6. Select **Approved Tool** and send the first message again: the line says "Sent as
   written".

Link to scene 2: "The employee kept working and the tool never saw the data. What does the
security team see?"

## Scene 2: Admin

*An admin sees what happened and changes the rules.*

1. Switch to **Admin**. Open **Monitor**: requests inspected, the share with sensitive
   data, what the firewall did with them, the events from scene 1, and sensitive data by
   team. Click an outcome such as **Blocked**, or a cell of the team table, and the list
   shows those events. No prompt text is stored beyond a masked snippet.
2. Click an event to open it, then **Show who sent this**: the name and team appear.
   Nothing records the lookup; a real deployment needs an audit trail and an approval
   step.
3. Open **Configure**. Everything is on one page, in four groups. A setting with a
   control changes on the spot; a row with an arrow opens in place.
   - **Agent tools**: the systems the agent reaches, each **Trusted** or **Untrusted**,
     and the email domains that may receive real values. Leave **Web** and **Mail**
     untrusted for scene 3: trusting them switches off what that scene shows.
   - **Protected data**: open **Terms**, **Document fingerprints** or **Patterns** to add
     one. Under **Patterns**, describe a format ("ticket numbers like TCK-123456") and
     click **Add with AI**. In **Test a prompt**, paste a text and press Enter to see what
     detection finds in it.
   - **Policy**: open **Rules** for the rules as one file. Describe a rule in plain
     language to draft it; **Activate** appears beside "Draft, not active" once the text
     differs from the active version. Below it, **Agent injection protection** (used in
     scene 3) and **Keep events for**, a number of days.
   - **AI tools**: change **Unapproved Tool** to **Approved**. On **Chat** (the admin has
     it too), the same message now goes out as written. Change it back afterwards.

Link to scene 3: "People are one side. The other is the company's own AI agents."

## Scene 3: Agent

*An in-house agent reads a web page that carries a hidden instruction.*

Stay signed in as **Admin** (only an admin can change the protection level).

Part one, protection on:

1. Open **Agent**. (**Agent injection protection** is at **Standard**, under
   **Configure**.)
2. Ask: `Summarise https://supplier-portal.example/news/payment-terms-2027`
3. Each tool call appears as a line in the conversation, under your request, in the
   order the agent made them. A line opens with a click to what was sent and what came
   back; the dot at its left is green (allowed), blue (sent with placeholders only),
   yellow (untrusted content or waiting for you) or red (blocked, or a prompt injection).
4. Open the red `web.fetch_page` line: the hidden instruction is marked. The banner
   **Session tainted** appears above the conversation, and a `mail.send_email` to an
   outside address is blocked.
5. Ask it to look up a client in the CRM: the result the model saw holds placeholders only.
   In the message box, switch from **You** to **Agent**: the whole conversation now reads
   as the agent's model saw it, with placeholders where you see names and numbers.

Part two, protection off:

6. Under **Configure**, set **Agent injection protection** to **Off**. Back on
   **Agent**, click **New session**.
7. Ask the same question. If the agent obeys the hidden instruction, `mail.send_email`
   goes out with a blue dot. Open **Sent emails**: the email holds placeholders, not
   one real value.
8. Set protection back to **Standard** and click **Clear** on **Sent emails**.

Closing line: "Detection is the second line. The first is that the model never held the
data."

## Notes for the presenter

- **The agent runs on the real model.** It may ignore the hidden instruction by itself;
  then nothing is sent and there is nothing to block. Rehearse scene 3 once beforehand.
- **Answers vary.** The three AI tools on the Chat page answer with the real model, so the
  wording of an answer changes from run to run.
- **Blocks can be overridden.** "Send with placeholders anyway" hides values, not a
  document: a blocked contract still leaves with its names and numbers masked.
- **The sample organisation** (`SEED_DEMO_DATA=true`) fills Monitor with two weeks of
  activity if you want numbers on screen before you start.
