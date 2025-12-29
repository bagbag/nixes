{ pkgs, inputs, ... }:
{
  environment.systemPackages = with pkgs; [
    nh
    e2fsprogs

    # Runtimes
    nodejs_latest
    deno

    # Development Tools
    podman-compose
    dbeaver-bin

    # Other Software
    ffmpeg
    gimp
    rclone
    remmina
    signal-desktop
    transmission_4-gtk
  ];
}
