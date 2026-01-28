{ config, pkgs, ... }:
{
  services.mongodb = {
    enable = true;
    package = pkgs.mongodb-ce;
    dbpath = "/var/lib/mongodb";
  };
}
