{
  pkgs,
  ...
}:
{
  environment.systemPackages = with pkgs; [
    battery-toolkit
    nodejs_latest
  ];
}
