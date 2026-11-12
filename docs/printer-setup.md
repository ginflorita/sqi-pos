# Receipt printer setup — one USB printer per laptop

Each cashier laptop remembers its own application printer. No printer purchase is required to install the update. Automatic printing stays off until an administrator finishes setup. Existing sales and stock are preserved.

## Set up each Windows laptop

1. Install the printer manufacturer's Windows driver and print a Windows test page. Select the paper size in the driver. The POS supports 58 mm and 80 mm receipt rolls plus Letter (8.5 × 11 in) for ordinary office printers. On Letter paper, the 80 mm receipt layout prints at its original size, centered at the top of the sheet.
2. Copy this application folder to the laptop and install Python if it is not installed. The print helper uses Python's standard library and Windows PowerShell; it does not run another POS database or server. Do not copy the main laptop's live database to the second laptop.
3. Sign in as administrator in the POS browser **on that laptop**. Open **Settings → Receipt printer · this laptop → Pair print helper**. Create the pairing code.
4. Double-click `Pair-Print-Helper.cmd` on that laptop. Enter the POS address shown in Settings and that laptop's pairing code. For LAN HTTPS, enter the local path to the trusted POS certificate PEM file, or leave it blank if the certificate is already trusted by Windows. Certificate and hostname verification remain enabled. HTTP is accepted only for localhost on the main laptop.
5. Keep the helper running. Close the pairing dialog, click **Refresh status**, then **Choose printer**. Select the detected printer, choose Letter, 58 mm, or 80 mm paper, and select **On — use this printer**. Save.
6. Check a saved receipt and use **Print another copy** to verify physical output and paper size before trading. This is an additional paper copy, recorded in history. No test page is sent automatically.
7. On the POS host laptop, a cashier can use **Connect printer** in Checkout whenever an enabled helper is offline. It starts in the background without an Administrator prompt. Repeat the one-time setup on a second laptop with its own browser pairing and USB printer; that laptop still starts `Start-Print-Helper.cmd` locally because a remote browser cannot launch a Windows program. Once configured, the helper reuses `.print-helper/config.json` without asking again. To change the POS address or pairing, double-click `Pair-Print-Helper.cmd` again.

Use the same browser profile for a cashier computer. A new browser profile needs its own printer pairing. A manager can sign out after setup and the cashier can sign in in the same profile.

## Checkout

- Cashier clicks **Confirm payment → Yes**. The sale and its single automatic print job are committed together.
- If an enabled helper is offline on the host laptop, **Connect printer** appears at the top of Checkout. Printer setup and disconnection are managed in Settings. Repeated clicks cannot start competing helper processes.
- The laptop helper pulls the job and sends the receipt, including the SQI logo and company details, to the saved Windows printer. No browser print dialog is opened.
- The receipt displays print status. **Queued** waits for the helper; **claimed** means it was handed to the helper; **submitted** means Windows accepted the document, not proof that paper came out. Driver, USB, paper, and printer errors still need physical checks.
- Settings shows waiting or interrupted jobs immediately. Completed and failed job records are kept under **View recent print history**, including failures that were already fixed.
- The helper contacts the host, so the browser does not need special localhost/network permissions or a browser extension. Printer credentials are separate from cashier sessions and remain scoped to one browser profile.
- Without completed setup, **Print / save PDF** remains available using the browser dialog.

## Interrupted printing and copies

Never take payment again to fix printing. The original sale remains saved.

Queued jobs are durable and print when the helper reconnects. A claimed job is never automatically sent a second time: a crash or lost response may happen after the printer received it. Check the printer and Windows queue. Stop the helper and cancel an unwanted Windows job before using **Settings → Review / close** to resolve a pending record. Resolving a record cannot recall paper already being printed. A manager must record what was checked. Then open the saved receipt and request **Print another copy** if necessary.

Browser printing and additional helper copies are blocked while a job for that sale is pending. Deliberate additional copies after completion are allowed and audited. No application can guarantee physical exactly-once paper output when the spooler/device acknowledgement is lost; the conservative review step prevents blind automatic retries.

Keep `.print-helper/config.json` private: it contains this laptop's helper token. Pairing again revokes the previous token and turns automatic printing off until configured again. Restore disables printer pairing and closes pending jobs from the snapshot, preventing old receipts from replaying after recovery. Re-pair both laptops after restoring.

To stop automatic printing on one laptop, sign in as manager on that laptop and select **Settings → Receipt printer → Disconnect printer**. Confirm the dialog. The pairing is revoked and the helper exits when it next contacts the server. Waiting jobs are marked failed so they will not print unexpectedly after reconnection; review their receipts before making another copy. If a job has already been handed to the helper, check its printer queue and use **Review / close** before disconnecting. To reconnect, create a new pairing code, double-click `Pair-Print-Helper.cmd`, and choose the printer again.

## Supported scope and verification

Windows desktop printers installed with a working driver are supported. Virtual PDF/XPS/Fax/OneNote queues cannot be enabled for automatic printing. Driver-specific cutter, cash drawer, and raw ESC/POS commands are not implemented. Receipt layout wraps long descriptions and splits long receipts into pages; verify actual driver margins/roll cutting when hardware is available.

Automated checks cover terminal isolation, manager-only setup, token revocation, one automatic job on checkout retries, lost acknowledgements, printer failures without repeated payment/stock changes, and Windows adapter compilation. Installed printer enumeration was checked without sending paper. Physical USB output remains to be tested after buying the printer.

Windows printing APIs: [installed printers](https://learn.microsoft.com/en-us/dotnet/api/system.drawing.printing.printersettings.installedprinters?view=netframework-4.8), [PrintDocument](https://learn.microsoft.com/en-us/dotnet/api/system.drawing.printing.printdocument?view=netframework-4.8).
