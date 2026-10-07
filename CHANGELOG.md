# Changelog

## 0.2.0

- **Automatic per game:** the game in front switches the trigger profile and Xbox mode by itself. Built-in .exe list for many games, "Remember for this game" for the rest; native DualSense games (Cyberpunk 2077, Sony ports, Silent Hill 2) turn Xbox mode off.
- **Sound to vibration (experimental):**
  - **HD haptics** for a DualSense on USB: the game's audio is sent to the controller's haptic channels (3–4), with the game's rumble mixed in as low tones. The app leaves the controller's rumble-emulation mode while this runs, which is what lets the audio through.
  - **Rumble motors** over USB and Bluetooth: bass → left, high sounds → right, on top of the game's own rumble.
  - Settings: HD or motors, which output to listen to, strength, sensitivity, and a test sound.
- **Light bar:** automatic color by mode (green = Xbox mode, blue = off, red = low battery), your own color, or off, with brightness.
- **Trigger kick:** optional short kick in both triggers when the game rumbles (DualSense).
- **More trigger effects and presets:** slope, multi-zone, bow, galloping and machine effects; 16 presets with clicks placed where Xbox games register a press; three Silent Hill f variants.
- **DualShock 4 support:** mapping, rumble, light bar, battery (adaptive triggers are DualSense-only). Not yet tested on hardware.
- Low-battery notification, update check, Settings tab.
- Xbox mode off no longer touches the triggers, so games with native DualSense support keep their own effects.
- Installer (`DualSenseBridge-Setup.exe`) that also installs ViGEmBus / HidHide, plus a portable zip.

## 0.1.0

- First public version: DualSense as a virtual Xbox 360 controller over USB and Bluetooth, analog triggers, rumble, HidHide hiding, experimental trigger profiles, window + tray app.
