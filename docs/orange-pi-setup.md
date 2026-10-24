# Orange Pi Setup

This setup makes the Orange Pi the gateway. That is required for per-user internet control.

```text
Client devices
  -> Router/AP Wi-Fi in bridge/AP mode, DHCP off, NAT off
  -> Orange Pi Ethernet LAN, 192.168.8.1
  -> Orange Pi USB Wi-Fi dongle connected to the main ISP
  -> Internet
```

If the router/AP stays in normal router/NAT mode, the Orange Pi may see only the router's IP address. In that layout the portal can run, but individual pause/connect control will not be reliable.

## 1. Install Packages

```bash
sudo apt update
sudo apt install -y python3 nftables dnsmasq conntrack
```

## 2. Find Interface Names

```bash
ip -br link
iw dev
```

Typical names:

```text
eth0  -> Orange Pi Ethernet connected to the AP/router LAN port
wlan0 -> USB Wi-Fi dongle connected to the main ISP
```

If your names differ, update the commands and service files below.

## 3. Connect The USB Wi-Fi Dongle To The ISP

Use your Orange Pi distro's network tool, for example:

```bash
sudo nmtui
```

Confirm the Orange Pi itself has internet through the USB Wi-Fi dongle:

```bash
ping -c 3 1.1.1.1
```

## 4. Configure The Ethernet LAN

Set the Ethernet side to a static gateway address. Replace `Wired connection 1` if needed.

```bash
nmcli connection show
sudo nmcli connection modify "Wired connection 1" ipv4.addresses 192.168.8.1/24
sudo nmcli connection modify "Wired connection 1" ipv4.method manual
sudo nmcli connection down "Wired connection 1"
sudo nmcli connection up "Wired connection 1"
```

If your image does not use NetworkManager, configure `eth0` with `192.168.8.1/24` using your distro's network settings.

## 5. Configure The Router/AP

On the router/AP that broadcasts the Wi-Fi:

```text
Mode: bridge/AP mode
DHCP server: off
NAT/routing: off
LAN cable: connect AP LAN port to Orange Pi eth0
```

The AP should not hand out addresses. The Orange Pi will do that with `dnsmasq`.

## 6. Configure DHCP/DNS On The Orange Pi

Copy the sample config:

```bash
sudo cp /home/orangepi/eco-con/systemd/dnsmasq-ecoconnect.conf /etc/dnsmasq.d/ecoconnect.conf
```

Edit `/etc/dnsmasq.d/ecoconnect.conf` if your LAN interface is not `eth0`.

Restart:

```bash
sudo systemctl restart dnsmasq
sudo systemctl enable dnsmasq
```

Clients should receive:

```text
IP address: 192.168.8.50-192.168.8.200
Gateway:    192.168.8.1
DNS:        192.168.8.1
Portal:     http://192.168.8.1:8080
```

## 7. Copy And Run The Project

From your PC:

```bash
scp -r eco-con orangepi@ORANGE_PI_IP:/home/orangepi/eco-con
```

From the Orange Pi:

```bash
cd /home/orangepi/eco-con
python3 portal.py --host 0.0.0.0 --port 8080
```

Open this from a phone connected to the AP Wi-Fi:

```text
http://192.168.8.1:8080
```

## 8. Install Services

Edit the portal service first:

```bash
nano /home/orangepi/eco-con/systemd/ecoconnect-portal.service
```

Replace:

```text
ECOCON_ADMIN_PASSWORD=change-this-password
```

If your upstream USB Wi-Fi is not `wlan0`, edit `systemd/ecoconnect-firewall.service` and change `--upstream-interface`.

Install:

```bash
sudo cp /home/orangepi/eco-con/systemd/ecoconnect-portal.service /etc/systemd/system/ecoconnect-portal.service
sudo cp /home/orangepi/eco-con/systemd/ecoconnect-firewall.service /etc/systemd/system/ecoconnect-firewall.service
sudo systemctl daemon-reload
sudo systemctl enable --now ecoconnect-portal
sudo systemctl enable --now ecoconnect-firewall
```

Check logs:

```bash
sudo systemctl status ecoconnect-portal
sudo systemctl status ecoconnect-firewall
journalctl -u ecoconnect-portal -f
journalctl -u ecoconnect-firewall -f
```

## 9. Validate The Gate

From a client connected to the AP Wi-Fi:

1. Open `http://192.168.8.1:8080`.
2. Add time.
3. Before pressing `Connect to the internet`, internet traffic should fail.
4. Press `Connect to the internet`; internet traffic should work.
5. Press `Pause time`; internet traffic should stop again within about one second.

On the Orange Pi, watch the nftables allow set:

```bash
sudo nft list set inet ecoconnect_filter allowed_clients
```

The client's IP appears only while connected and not expired.

## Notes

The current top-up buttons are manual. In a public deployment, replace `/api/topup` calls with real sensor events or protected machine-side controls, otherwise users can award themselves time from the browser.

This project intentionally gates IP forwarding. It does not implement a full HTTPS captive portal. Users can always reach the portal directly at `http://192.168.8.1:8080` or `http://portal.ecoconnect:8080`.
