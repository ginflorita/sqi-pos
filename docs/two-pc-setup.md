# Two-PC POS setup

Saved: 2026-10-20 (Asia/Taipei).

The main PC runs the POS and stores the shared database. The second PC only needs a browser. Both PCs use the same products, stock, and sales records through the main PC.

The main PC's network address checked on 2026-10-20 was **192.168.1.115**. Confirm this address before following the commands, especially after moving to the bazaar's router. Use the main PC's actual router-network IPv4 address if it has changed.

## 1. Connect both PCs

Connect both PCs to the same router/Wi-Fi. Keep the main PC powered on, awake, and connected while either cashier is working. Internet is not required during checkout.

## 2. Create the HTTPS certificate on the main PC

Open PowerShell and run:

```powershell
cd "F:\CODEX-POS EXCEL"
python tools/certificate.py --ip 192.168.1.115
```

Use the actual main-PC address in place of `192.168.1.115` when necessary. The command creates `certs/pos.crt` and `certs/pos.key` and prints the certificate fingerprint. It refuses to overwrite existing certificate files; see the notes below if changing networks.

## 3. Install the certificate on both PCs

Copy `certs/pos.crt` to the second PC. Keep `pos.key` on the main PC under the owner's protected Windows account.

On each PC, inspect the certificate and compare its SHA256 fingerprint with the creation command's output. Then double-click `pos.crt` and choose:

**Install Certificate → Current User → Place all certificates in the following store → Trusted Root Certification Authorities → Finish**

Install it under the Windows account that will use the browser. Resolve certificate warnings before entering cashier credentials.

## 4. Start the POS in network mode

Stop the current POS server first. If it is running in a terminal, press **Ctrl+C** in that terminal. Then run on the main PC:

```powershell
cd "F:\CODEX-POS EXCEL"
.\Start-POS.cmd --lan --cert certs/pos.crt --key certs/pos.key
```

Keep the server running while either PC uses the POS.

## 5. Allow the local connection through Windows Firewall

On the main PC, have the owner allow inbound **TCP port 8765** for the **Private** network profile, restricted to the **local subnet**. Use the trusted router's private network, with no internet port forwarding.

The application does not automatically change firewall or certificate trust settings.

## 6. Open the POS in each browser

| Device | Browser address |
| --- | --- |
| Main PC | `https://localhost:8765` |
| Second PC | `https://192.168.1.115:8765` |

Use the main PC's actual network address on the second PC. `localhost` always refers to the PC using that browser. Keep a consistent browser address for device approval and pending-payment recovery.

If setup is incomplete, create the manager account on the main PC. When switching from HTTP to HTTPS, sign out and back in to refresh the authentication cookies for HTTPS.

## 7. Create and approve the second cashier

1. On the main PC, sign in as the manager and open **Team & laptops → Add account**.
2. Create the second person's named cashier account.
3. Sign in with that account on the second PC and enter its laptop name.
4. On the main PC, approve the pending laptop from **Team & laptops**.

Clearing browser cookies or changing browser profiles requires laptop approval again.

## 8. Begin the business day

The manager opens the bazaar day. Each cashier opens a separate shift and records their own drawer's opening cash. Both PCs now conduct sales against the shared records on the main PC.

## Keep the host address consistent

Reserve the main PC's address in the router so it stays consistent. A different bazaar router may assign a different address. If the address changes, create a new certificate in a new folder, trust it on both PCs, and start the server with that folder's files. For example:

```powershell
python tools/certificate.py --ip 192.168.1.115 --output certs-bazaar
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
