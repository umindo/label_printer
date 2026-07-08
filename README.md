# Label Printer

Print TSPL item labels directly from an ERPNext **Delivery Note** to a **TSC TDP-225** printer connected to a Raspberry Pi 3B.

Compatible with **ERPNext v15 and v16**.

---

## 🚀 Installation

### 1. Install App on ERPNext Bench

On your ERPNext server, run:

```bash
bench get-app https://github.com/<your-username>/label_printer
bench --site <your-site> install-app label_printer
bench --site <your-site> migrate
```

### 2. Set Up Raspberry Pi Print Agent

1. Copy the `print_agent/` directory from the app onto your Raspberry Pi.
2. Run the auto-setup script on the Pi:
   ```bash
   cd print_agent
   bash setup.sh
   ```
3. Copy the secure **API Key** generated at the end of the script.

### 3. Configure ERPNext

1. Go to **Label Printer Settings** in ERPNext.
2. Enter the IP of your Raspberry Pi, Port `5000`, and paste the **API Key**.
3. Set label size (default `60mm` width, `40mm` height, `3mm` gap).
4. Click **Test Connection** to confirm connectivity, then **Save**.
