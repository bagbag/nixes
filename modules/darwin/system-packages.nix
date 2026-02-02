{
  pkgs,
  ...
}:
{
  environment.systemPackages = [
    pkgs.battery-toolkit
  ];
}
