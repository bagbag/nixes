{ config, ... }:
{
  # Sizing comes from nstdl's defaults.

  # Phase 1 of the two-phase switch on this machine; remove and switch again.
  # nstdl.linuxBuilder.bootstrap = true;

  nstdl.linuxBuilder.sandboxSecrets.tstdl-npm-token = {
    sourceFile = config.age.secrets.tstdl-npm-token.path;
    path = "/var/lib/nix-npm-credentials/tstdl-token";
  };
}
