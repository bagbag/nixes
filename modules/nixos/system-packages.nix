{
  pkgs,
  inputs,
  config,
  lib,
  ...
}:
{
  environment.systemPackages =
    with pkgs;
    [
      deploy-rs
      e2fsprogs
      usbutils
    ]
    ++ (lib.optionals (!config.modules.system.installMode) [
      # Runtimes
      nodejs_latest
      deno

      # Development Tools
      podman-compose
      dbeaver-bin
      rustup
      gcc

      # Other Software
      ffmpeg
      gimp
      poppler-utils
      qpdf
      rclone
      remmina
      rustdesk-flutter
      signal-desktop
      bitwarden-desktop
      transmission_4-gtk
    ]);
}
