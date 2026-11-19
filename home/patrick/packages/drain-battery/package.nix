# Drains the battery to a target while plugged in, then re-enables the adapter.
# batt comes from Homebrew, so the script keeps the ambient PATH.
{ writeShellApplication }:
writeShellApplication {
  name = "drain-battery";
  text = builtins.readFile ./drain-battery.sh;
}
