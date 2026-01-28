{ pkgs, inputs, ... }:
{
  environment.systemPackages = with pkgs; [
    deploy-rs
    e2fsprogs
    usbutils

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
    transmission_4-gtk
  ];
}
