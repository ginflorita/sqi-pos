# Two-PC POS setup

Saved: 2026-10-20 (Asia/Taipei).

The main PC runs the POS and stores the single shared database. Each PC can open it in a dedicated Chrome or Edge app window without tabs or an address bar. Each laptop also runs its own print helper if automatic USB printing is enabled.

| Component | Main laptop | Second laptop |
| --- | --- | --- |
| POS server and application dependencies | Install here | Not needed |
| SQLite database | Stored in `data/pos.sqlite3` here | Do not install or copy a separate database |
| Chrome or Microsoft Edge | Required for the app window | Required for the app window |
| Python | Required; tested with 3.13 | Required only for the print helper |
| USB printer driver and print helper | For this laptop's printer | For this laptop's printer |

SQLite is included with Python. No separate SQLite, SQL Server, Access, or MySQL installation is required.

The commands below use **192.168.1.115 as an example**. On the main laptop, run `ipconfig` and find the active Wi-Fi/Ethernet IPv4 address. Use the main laptop's actual router-network address, especially after moving to the bazaar's router.

## 0. Install the main laptop first

Initial downloads need internet. Normal checkout works without internet once both laptops are connected to the router.

1. Install [Python Install Manager from the official Windows downloads](https://www.python.org/downloads/windows/).
2. Open a new Command Prompt or PowerShell window and run:

   ```powershell
   py install 3.13
   py -3.13 --version
   ```

   If using a traditional Python installer instead, select **Add python.exe to PATH**, then reopen the terminal and check `python --version`.
3. Download the latest [SQI POS source](https://github.com/ginflorita/sqi-pos) using **Code → Download ZIP**, and extract it to a local folder such as `C:\SQI-POS`. Open the extracted folder containing `Install-POS.cmd`; do not run it from inside the ZIP.
4. Double-click **Install-POS.cmd**. It creates `.venv` and installs the application dependencies. If Python is not detected, follow the troubleshooting section at the end of this guide.
5. Double-click **Start-POS.cmd** and open `http://localhost:8765`. Create the manager account if this is a new installation. Keep the server window open.
6. Stop that server with **Ctrl+C** before starting network mode in step 4 below.

### Moving existing records to a new main laptop

Create a verified backup from Settings first. Stop the old server before copying its complete **data** folder into the new main laptop's application folder. Copy the **backups** folder separately for recovery. The live database and uploaded images are not included in the GitHub download. Do not start two server copies against separate copies of the records; choose one main laptop.

## 1. Connect both PCs

Connect both PCs to the same router/Wi-Fi. Keep the main PC powered on, awake, and connected while either cashier is working. Internet is not required during checkout.

## 2. Create the HTTPS certificate on the main PC

Open PowerShell and run:

```powershell
cd "C:\SQI-POS"
.\.venv\Scripts\python.exe tools/certificate.py --ip 192.168.1.115
```

Replace `C:\SQI-POS` with the actual extracted project folder. Use the actual main-PC address in place of `192.168.1.115`. The command creates `certs/pos.crt` and `certs/pos.key` and prints the certificate fingerprint. It refuses to overwrite existing certificate files; see the notes below if changing networks.

## 3. Install the certificate on both PCs

Copy `certs/pos.crt` to the second PC. Keep `pos.key` on the main PC under the owner's protected Windows account.

On each PC, inspect the certificate and compare its SHA256 fingerprint with the creation command's output. Then double-click `pos.crt` and choose:

**Install Certificate → Current User → Place all certificates in the following store → Trusted Root Certification Authorities → Finish**

Install it under the Windows account that will use the app window. Resolve certificate warnings before entering cashier credentials.

## 4. Start the POS in network mode

Stop the current POS server first. If it is running in a terminal, press **Ctrl+C** in that terminal. Then run on the main PC:

```powershell
cd "C:\SQI-POS"
.\Start-POS.cmd --lan --cert certs/pos.crt --key certs/pos.key
```

Keep the server running while either PC uses the POS. After verifying HTTPS, stop the manual server with **Ctrl+C**, then double-click **Setup-Host-Shortcut.cmd** once on the main laptop. It creates a **Start SQI POS** desktop icon and a Windows sign-in startup shortcut for the server. The icon starts LAN HTTPS automatically when `certs/pos.crt` and `certs/pos.key` are present, then opens the POS app window.

## 5. Allow the local connection through Windows Firewall

On the main PC, have the owner allow inbound **TCP port 8765** for the **Private** network profile, restricted to the **local subnet**. Use the trusted router's private network, with no internet port forwarding.

The application does not automatically change firewall or certificate trust settings.

## 6. Open the POS app window

| Device | Address used by the app window |
| --- | --- |
| Main PC | `https://localhost:8765` |
| Second PC | `https://192.168.1.115:8765` |

Use the main PC's actual network address on the second PC. `localhost` always refers to the PC using that window. Keep a consistent address and browser profile for pending-payment recovery. The dedicated window uses the default Chrome or Edge profile, so it retains that profile's sign-in and saved ticket state. If a shift is open in another browser profile, close and reconcile that shift before opening a new one.

On the second laptop, extract a fresh copy of the application files. Do not copy the main laptop's `data` folder, backups, or private `certs/pos.key`. Double-click **Create-Cashier-Shortcut.cmd** there and enter the main laptop's reserved IP address (without `https://`). It creates **SQI POS Cashier** on that laptop's desktop. Double-click that icon to open the shared POS without browser tabs or an address bar. Do not run `Start-POS.cmd` on the second laptop.

If setup is incomplete, create the manager account on the main PC. When switching from HTTP to HTTPS, sign out and back in to refresh the authentication cookies for HTTPS.

## 7. Create the second cashier account

1. On the main PC, sign in as the manager and open **Team → Add account**.
2. Create the second person's named cashier account.
3. Sign in with that account on the second PC. A correct username and password grant access immediately.

A different browser profile can also sign in, but it gets a separate local shift and printer pairing.

## 8. Begin the business day

The manager opens the bazaar day. Each cashier opens a separate shift and records their own drawer's opening cash. Both PCs now conduct sales against the shared records on the main PC.

## 9. Set up each USB receipt printer

Once the printers are available, follow [printer setup](printer-setup.md) on **each laptop**. Install each printer's Windows driver, then pair and run `Start-Print-Helper.cmd` and choose its printer in Settings.

The second laptop can use a downloaded copy of the application source for the helper files. Install Python there, but **do not run Install-POS.cmd or Start-POS.cmd there**. Its helper connects to the main laptop's HTTPS address and does not need a local database. Keep `pos.key` on the main laptop; copy only the public certificate `pos.crt` to the second laptop.

## 10. Daily startup and shutdown

1. Connect both laptops to the same router.
2. Sign in to Windows on the main laptop. The startup shortcut starts the server automatically; its desktop **Start SQI POS** icon also starts it if needed. Keep the laptop awake and plugged in.
3. If using automatic printing, run `Start-Print-Helper.cmd` on each laptop.
4. Double-click **Start SQI POS** on the main laptop and **SQI POS Cashier** on the second laptop. Sign in, open the business day, and open each cashier's shift.
5. At closing, finish orders, reconcile and close shifts, close the business day, and verify the backup. Keep an additional recovery copy on a separate drive.

## Updating application files later

Back up first and finish all payments before replacing application files. Preserve the existing `data`, `backups`, `certs` (or your certificate folder), and `.print-helper` folders. Do not replace them with empty folders from a new download. After copying the update, double-click **Start SQI POS** on the main laptop. It detects and replaces its older running server; closing only the app window does not stop that server. The second laptop reconnects and reloads when the new server is ready. If application dependencies change, run `Install-POS.cmd` again on the main laptop before starting. The second laptop still uses the main laptop's single database.

## Keep the host address consistent

Reserve the main PC's address in the router so it stays consistent. A different bazaar router may assign a different address. If the address changes, create a new certificate in a new folder, trust it on both PCs, and start the server with that folder's files. For example:

```powershell
.\.venv\Scripts\python.exe tools/certificate.py --ip 192.168.1.115 --output certs-bazaar
.\Start-POS.cmd --lan --cert certs-bazaar/pos.crt --key certs-bazaar/pos.key
```

Replace the IP with the newly assigned address. Stop the running server before starting it again.

See [Operations](operations.md) for daily use, external backups, restore, and recovery of an unavailable laptop.

## If installation says Python was not found

That message means Windows could not start a Python runtime; it can be a missing installation or a PATH/Store-alias conflict. Disabling the Store alias by itself does not install Python.

1. Install Python from the [official Windows downloads](https://www.python.org/downloads/windows/). This POS is tested with Python 3.13.
2. If using Python Install Manager, open a new terminal after installing it and run `py install 3.13` to install the runtime. If using a traditional Python installer, select **Add python.exe to PATH**.
3. Close and reopen the terminal. Check `py -3.13 --version` or `python --version`.
4. Run `Install-POS.cmd` again on the main laptop.

The updated installation/start commands check a working `python` first, then the `py` launcher, and show a specific Python setup message when neither works. The second laptop only needs Python if using the local print helper. Keep the existing `data` folder when updating application files.

Official reference: [Python on Windows](https://docs.python.org/3/using/windows.html).
