# HRMS Middleware — Easy Installation Guide

**For:** Anyone setting this app up on a Windows 11 PC for the first time.
**Skill level required:** None. If you can copy-paste, you can do this.
**Time required:** 15–20 minutes (most of which is the PC doing work in the background).

> What this app does, in plain English: It runs on a PC that sits on the same
> Wi-Fi/LAN as your biometric attendance machine. Your HRMS web app then talks
> to *this* app, and this app talks to the machine. You don't need to be near
> the machine to use it — once this PC is set up, everything happens through
> this app over the internet.

---

## What you need before you start

| You need | How to check | What to do if missing |
|---|---|---|
| A Windows 10 or Windows 11 PC | Press `Win + Pause` → look at "Edition" | Use any modern Windows PC. |
| An internet connection on that PC | Open a browser, load any website | Connect to Wi-Fi / Ethernet first. |
| Permission to install software (Administrator) | Try installing anything from Microsoft Store | Ask the PC owner for the admin password. |
| The PC is on the **same Wi-Fi / LAN** as the biometric machine | Ping the machine: `ping 192.168.x.x` from this PC | Connect the PC to the same network the biometric machine is on. |

You do **not** need: Visual Studio, VS Code, Python knowledge, programming
experience, GitHub account.

---

## The 5 steps (high level)

1. Open **PowerShell as Administrator**.
2. Install **Git** (one command).
3. **Download** the app (one command).
4. **Install everything else automatically** (one command).
5. **Check it's working** (open a webpage).

Below, each step has the *exact* command to copy. Don't worry about the words
— just paste each block, press Enter, and wait for it to finish before pasting
the next one.

---

## STEP 1 — Open PowerShell as Administrator

1. Press the **Windows key** on your keyboard.
2. Type the word: `powershell`
3. You'll see "Windows PowerShell" in the search results.
4. **Right-click** on it → click **"Run as administrator"**.
5. A dark-blue window will open. If Windows asks "Do you want to allow this app to make changes?", click **Yes**.

You should now see a window with a line that looks like this:

```text
PS C:\Windows\system32>
```

That blinking cursor at the end is where you'll paste commands. Click anywhere
inside that window so it's "in focus" before pasting.

### How to paste a command

- **To copy** from this document: select the text and press `Ctrl + C`.
- **To paste** into PowerShell: just **right-click** anywhere inside the
  PowerShell window. (Don't use `Ctrl + V` — right-click is the standard way
  in PowerShell.)
- **To run** the pasted command: press **Enter**.

### One-time settings command (paste this first)

This tells PowerShell to allow our setup scripts to run during this session.
Paste it, press Enter, and you'll get no output (that's normal — silence means
success):

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
```

---

## STEP 2 — Install Git

Git is the tool that downloads the app from the internet. We install it once.

Paste this single line, press Enter, and wait. It will download and install
silently. You'll see some progress text — wait until you see the `PS C:\...>`
prompt come back (about 1–2 minutes):

```powershell
winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements
```

### What if `winget` is "not recognized"?

This means your Windows is missing the App Installer tool. Do this:

1. Open **Microsoft Store** (search for it in the Start menu).
2. Search for **"App Installer"**.
3. Click **Get** / **Update**.
4. Wait until install finishes.
5. **Close PowerShell completely**, then redo **STEP 1** to reopen it as Admin.
6. Re-paste the winget command above.

### Verify Git is installed

Close PowerShell, reopen it (as Administrator again — Step 1), and paste:

```powershell
git --version
```

You should see something like:

```text
git version 2.43.0.windows.1
```

If you see a version number, Git is good. Move to Step 3.

> **Why did we close and reopen?** When a new program is installed, the
> PowerShell window doesn't know about it until you reopen the window. This
> is a one-time annoyance.

---

## STEP 3 — Download the app from GitHub

Now we'll download the app to a folder called `C:\HRMS_Middleware`. We're
using `C:\` because it's the easiest place to find later. You can change it
later if you want.

Paste these **four lines together** (just copy the whole block), then press
Enter:

```powershell
cd C:\
New-Item -ItemType Directory -Force -Path "C:\HRMS_Middleware" | Out-Null
cd C:\HRMS_Middleware
git clone https://github.com/toyogt/HRMS.git
```

You'll see lines like `Cloning into 'HRMS'...` and `Receiving objects: ...
100%`. This takes 30 seconds to 2 minutes depending on your internet speed.

When the prompt `PS C:\HRMS_Middleware>` comes back, the download is done.

Now move into the project folder:

```powershell
cd "C:\HRMS_Middleware\HRMS\HR Module"
```

The folder is named `HR Module` with a **space**. The double quotes around the
path are important — don't remove them.

Verify you're in the right place by paste this:

```powershell
ls .\INSTALL_ONE_CLICK.cmd
```

You should see one row of output mentioning `INSTALL_ONE_CLICK.cmd`. If you
get an error like "Cannot find path", you're in the wrong folder — repeat the
`cd "C:\HRMS_Middleware\HRMS\HR Module"` line above.

---

## STEP 4 — Run the one-click installer

This is the magic step. **One single command** does all of this for you:

- Installs Python 3.11 (the programming language the app is written in).
- Installs Microsoft Visual C++ runtime (a system library the app needs).
- Creates a private Python "virtual environment" so this app doesn't conflict with anything else on your PC.
- Downloads and installs ~30 Python packages the app depends on.
- Opens port 9100 in Windows Firewall so other devices on your network can reach the app.
- Registers a **scheduled task** so the app starts automatically every time the PC boots.
- Actually starts the app.

Paste this one line:

```powershell
.\INSTALL_ONE_CLICK.cmd
```

Now **wait**. Be patient — this takes 3 to 8 minutes the first time. You will
see a lot of text scroll by. That's normal. Some of it will be yellow or green
warnings. That's also normal.

If Windows pops up a UAC dialog ("Do you want to allow this app...?"), click
**Yes**.

You'll know it's done when:

- The text stops scrolling.
- You see a green line like: `Setup complete.`
- You see lines like: `API base: http://127.0.0.1:9100` and `Swagger docs: http://127.0.0.1:9100/docs`.
- Your `PS C:\...HR Module>` prompt comes back.

> **DO NOT close the PowerShell window during installation.** If you close
> it accidentally, just reopen PowerShell as Admin (Step 1), `cd` back into
> the project folder (`cd "C:\HRMS_Middleware\HRMS\HR Module"`), and run
> `.\INSTALL_ONE_CLICK.cmd` again. It's safe to re-run.

---

## STEP 5 — Check that it's running

Open your favourite browser (Chrome, Edge, Firefox — anything) and visit:

```text
http://127.0.0.1:9100/health
```

You should see a JSON page like:

```json
{
  "status": "ok",
  "env": "dev",
  "db_dialect": "sqlite",
  "outbox": { "PENDING": 0, "PROCESSING": 0, "SENT": 0, "FAILED": 0 }
}
```

If you see this, **the app is running**. Congratulations.

### Useful pages

| What you want to see | URL |
|---|---|
| Health check (machine-readable) | `http://127.0.0.1:9100/health` |
| Built-in dashboard (employees + attendance) | `http://127.0.0.1:9100/dashboard` |
| Interactive API documentation (Swagger) | `http://127.0.0.1:9100/docs` |
| List of registered biometric devices | `http://127.0.0.1:9100/api/v1/devices` (needs API key — see below) |

### Test it from PowerShell too

Back in PowerShell, paste:

```powershell
curl.exe http://127.0.0.1:9100/health
```

You'll see the same JSON. Then:

```powershell
curl.exe -H "x-api-key: dev-middleware-key" http://127.0.0.1:9100/api/v1/devices
```

You should see `{"rows":[]}` (an empty list — that's correct; no devices have
been registered yet).

---

## STEP 6 — Make it accessible from the internet (OPTIONAL)

By default the app only listens on `127.0.0.1`, which means only this PC can
reach it. If your HRMS web app is hosted online and needs to reach this PC,
you have two options:

### Option A — Cloudflare Tunnel (recommended, free, no router changes)

Re-run the installer with one extra flag. From the same PowerShell window:

```powershell
.\INSTALL_ONE_CLICK.cmd -EnableCloudflareTunnel
```

After it finishes, find your public URL by pasting:

```powershell
Get-Content .\var\logs\cloudflared.log -Tail 80
```

Look for a line containing `https://something.trycloudflare.com`. That's your
public URL. You can share it with the HRMS web app.

> **Note:** This URL is **temporary** (changes every restart). For a permanent
> URL, contact your administrator to set up a Cloudflare account and provide
> a tunnel token, then re-run:
>
> ```powershell
> .\INSTALL_ONE_CLICK.cmd -EnableCloudflareTunnel -CloudflareToken "<your-token-from-cloudflare>"
> ```

### Option B — Same local network only

If your HRMS app is also on the same LAN, the firewall rule that the installer
created already allows other LAN devices to connect. They use the LAN IP of
this PC:

```powershell
ipconfig | findstr IPv4
```

Look at the first `IPv4 Address . . . . . . . . . . . : 192.168.x.x`. Tell
your HRMS app to use `http://192.168.x.x:9100`.

---

## STEP 7 — Make sure the app restarts when the PC reboots

The one-click installer **already did this** for you. To prove it:

```powershell
schtasks /Query /TN "HRMS-Middleware-Supervisor" /V /FO LIST
```

You'll see a long list of task details. Look for `Status: Running`.

To **really** test it, restart the PC, wait 30 seconds after login, then open
your browser to `http://127.0.0.1:9100/health` again. You should still see
`status: ok`. No need to re-run any setup.

---

## How to check status later

Whenever you want to confirm everything's healthy, open PowerShell (it
doesn't need to be Admin for status checks), then:

```powershell
cd "C:\HRMS_Middleware\HRMS\HR Module"
.\scripts\status.ps1
```

You'll see a colour-coded summary of running processes and ports.

---

## How to stop and restart the app

**To stop the auto-running app temporarily:**

```powershell
schtasks /End /TN "HRMS-Middleware-Supervisor"
```

**To start it again:**

```powershell
schtasks /Run /TN "HRMS-Middleware-Supervisor"
```

**To turn off auto-start permanently** (the app won't start on next reboot):

```powershell
cd "C:\HRMS_Middleware\HRMS\HR Module"
.\scripts\remove_autostart.ps1
```

---

## How to update the app to the latest version

When a new version is published on GitHub, run:

```powershell
cd "C:\HRMS_Middleware\HRMS\HR Module"
git pull
.\INSTALL_ONE_CLICK.cmd
```

That's it. The installer detects the existing setup and only updates what's
changed.

---

## Where do my files live?

| What | Where |
|---|---|
| The whole app | `C:\HRMS_Middleware\HRMS\HR Module\` |
| Logs (if something goes wrong, look here) | `C:\HRMS_Middleware\HRMS\HR Module\var\logs\` |
| Local SQLite database (attendance + employees) | `C:\HRMS_Middleware\HRMS\HR Module\attendance.db` |
| Config file (port, API keys, etc.) | `C:\HRMS_Middleware\HRMS\HR Module\configs\dev.yaml` |
| The auto-start scheduled task | Windows Task Scheduler → `HRMS-Middleware-Supervisor` |

---

## Troubleshooting (real-world problems)

### Problem: "winget is not recognized"
**Fix:** Install **App Installer** from Microsoft Store, then close and reopen PowerShell as Administrator.

### Problem: The browser shows "This site can't be reached" at http://127.0.0.1:9100/health
Check three things in this order:

1. **Is the app actually running?**
   ```powershell
   cd "C:\HRMS_Middleware\HRMS\HR Module"
   .\scripts\status.ps1
   ```
   If nothing is running, start it: `schtasks /Run /TN "HRMS-Middleware-Supervisor"` and wait 10 seconds.

2. **Is something else using port 9100?**
   ```powershell
   netstat -ano | findstr :9100
   ```
   If you see another program holding the port, either close that program or change `ingress_port` in `configs\dev.yaml` to a free port like `9101`, then re-run the installer.

3. **Look at the error log:**
   ```powershell
   Get-Content .\var\logs\gateway.err.log -Tail 50
   ```
   The last 50 lines usually tell you exactly what's wrong.

### Problem: Installation finished but the app didn't auto-start
Run the installer once more with the start-now flag:

```powershell
cd "C:\HRMS_Middleware\HRMS\HR Module"
.\INSTALL_ONE_CLICK.cmd
```

It's safe to re-run any number of times.

### Problem: I want to change the port from 9100 to something else
1. Open `configs\dev.yaml` in Notepad:
   ```powershell
   notepad .\configs\dev.yaml
   ```
2. Find the line `ingress_port: 9100`, change `9100` to the port you want (e.g., `9200`).
3. Save and close Notepad.
4. Re-run the installer:
   ```powershell
   .\INSTALL_ONE_CLICK.cmd
   ```

### Problem: "I copied the entire folder from another PC instead of using `git clone`"
That can corrupt the Python virtual environment. The one-click installer detects this and rebuilds it automatically — just run it once and let it finish:

```powershell
cd "C:\HRMS_Middleware\HRMS\HR Module"
.\INSTALL_ONE_CLICK.cmd
```

### Problem: The Cloudflare URL changed and my HRMS app stopped working
Cloudflare's **quick tunnels** give a new URL every time the service restarts. For a stable URL, switch to a Cloudflare **named tunnel** (free Cloudflare account required) and use:

```powershell
.\INSTALL_ONE_CLICK.cmd -EnableCloudflareTunnel -CloudflareToken "<token-from-cloudflare-dashboard>"
```

### Problem: I want to uninstall everything
```powershell
cd "C:\HRMS_Middleware\HRMS\HR Module"
.\scripts\remove_autostart.ps1
```

Then delete the folder:

```powershell
cd C:\
Remove-Item -Recurse -Force "C:\HRMS_Middleware"
```

To also remove Python and Git that we installed:

```powershell
winget uninstall --id Python.Python.3.11
winget uninstall --id Git.Git
```

---

## Where to find help

- **Logs:** `C:\HRMS_Middleware\HRMS\HR Module\var\logs\` — the file `gateway.err.log` is the most useful when something's wrong.
- **Built-in docs in the same folder:**
  - `docs\API_INTEGRATION_GUIDE.md` — how to call the APIs from your web app.
  - `docs\API_Details_For_SE.md` — full technical reference for developers.
  - `docs\FRESH_WINDOWS_SETUP_GUIDE.md` — alternative setup notes.
- **Source code on GitHub:** [https://github.com/toyogt/HRMS](https://github.com/toyogt/HRMS)

---

## Cheat sheet (everything in one place)

If you ever need to do this again on a fresh PC, here is the *entire*
sequence:

```powershell
# 1. Open PowerShell as Administrator
Set-ExecutionPolicy -Scope Process Bypass -Force

# 2. Install Git
winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements

# 3. Close PowerShell, reopen as Administrator, then:
cd C:\
New-Item -ItemType Directory -Force -Path "C:\HRMS_Middleware" | Out-Null
cd C:\HRMS_Middleware
git clone https://github.com/toyogt/HRMS.git
cd "C:\HRMS_Middleware\HRMS\HR Module"

# 4. Run the one-click installer
.\INSTALL_ONE_CLICK.cmd

# 5. Verify in a browser:
#    http://127.0.0.1:9100/health   ← should say "status": "ok"
#    http://127.0.0.1:9100/dashboard
```

That's everything. The app is now installed, running, and will keep running
forever — even after reboots.
