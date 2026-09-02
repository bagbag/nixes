{ config, ... }:
{
  nstdl.accounts.users.patrick.hashedPasswordFile = config.age.secrets.patrick-password-hash.path;
  security.pam.services.gdm-password.enableGnomeKeyring = true;
}
