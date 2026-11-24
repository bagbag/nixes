# `nix build .#agent-setup`: the agent config as a tarball for people without this nix config.
# `nix flake check`: the agent config's full validator (the switch runs only its core check).
# `nix develop .#agent-tests`: the tools and python (pytest with xdist) to run its tests in a checkout.
{ inputs, ... }:
let
  self = inputs.self;
  rev = self.shortRev or self.dirtyShortRev or "local";
  date = builtins.substring 0 8 (self.lastModifiedDate or "00000000");
in
{
  perSystem =
    { pkgs, ... }:
    let
      agents = pkgs.callPackage ../../home/patrick/agents-package.nix { version = "${date}-${rev}"; };
    in
    {
      packages.agent-setup = agents.setup;
      checks.agent-configs = agents.checks;
      devShells.agent-tests = pkgs.mkShellNoCC { packages = agents.testInputs; };
    };
}
