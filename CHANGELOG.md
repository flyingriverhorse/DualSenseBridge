# Changelog

## 0.3.0

- **Profile editor** (new tab): build L2 / R2 effects with sliders, see them on a 10-zone strip with your trigger's position, and feel every change on the controller live (Xbox mode on or off; it stops when you leave the tab). Save them as your own profiles (★), kept in your user folder (`my_profiles.json` under AppData) so updates never overwrite them. **Copy JSON** to share one.
- **Add any game:** give your profile the game's .exe (**Browse…** or **Game in front**) and it switches on by itself when the game starts, also for games that are not in the built-in list. It replaces an earlier "Remember for this game" for that .exe.
- **Controls** (new tab): deadzone per stick (radial, no jump at the edge), trigger deadzone and full-press point, and remap any button to any Xbox button, LT/RT full press or nothing (e.g. Touchpad → Back). The defaults behave exactly as before.
- **Gyro aiming** (new tab): turn the controller to move the right stick, so it works in any Xbox game. Active while L2 is held, always, while L1 is held or while touching the touchpad; turn or lean; invert; sensitivity, jitter filter and game-deadzone skip; automatic drift correction and a Calibrate button. DualSense and DualShock 4, USB and Bluetooth.
- **HD haptics over Bluetooth (experimental):** the game's sound drives the actuators over Bluetooth too (report 0x32, 3 kHz, protocol research by SAxense). The game's rumble is mixed in as tones. USB stays the best quality.
- Fixed the update check and the "Releases" link: they pointed to an old repository name and always failed. 0.2.0 cannot tell you about this release, so update by hand once.
- Automated tests (315, no controller or driver needed) for report parsing, output reports and CRC, trigger effects, every profile, mapping, gyro, Bluetooth haptics and the engine loop. GitHub Actions runs them on every push and before every release build.
- README screenshots for every tab.

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
