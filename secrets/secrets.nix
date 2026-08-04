let
  nixstation = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMM/o1cLFjnD1m41DE41yWySYzOjvN7MizVJLIpbhbXN";
  nixbook-air = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBAZNTeHlIEMl2ILVsUjmWwptaTSSLOQRx0Xpeci562a";
  macbook-pro = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIC8IGUs9pgbtktVQcbmaIOXv6DQfDxtjvu+wds9JrEJu";
  nixmobil = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICvnCyc7hK0Tb5bXujzcjF+FjpmGi4FnfD9y84RtU6ZQ";

  keys = [
    nixstation
    nixbook-air
    macbook-pro
    nixmobil
  ];
in
{
  "awscli-insolytix-s3-secret-key.age".publicKeys = keys;
}
