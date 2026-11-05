# `nix build .#agent-setup`: the agent config as a tarball for people without this nix config.
{ inputs, ... }:
let
  self = inputs.self;
  rev = self.shortRev or self.dirtyShortRev or "local";
  date = builtins.substring 0 8 (self.lastModifiedDate or "00000000");
in
{
  perSystem =
    { pkgs, ... }:
    {
      packages.agent-setup =
        (pkgs.callPackage ../../home/patrick/agents-package.nix { version = "${date}-${rev}"; }).setup;
    };
}
