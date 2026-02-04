{ pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    jq
    sshfs
  ];
}
