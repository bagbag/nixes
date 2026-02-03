{ pkgs, ... }:
{
  environment.systemPackages = [
    pkgs.sshfs
  ];
}
