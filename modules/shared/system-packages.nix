{ pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    bc
    jq
    sshfs
  ];
}
