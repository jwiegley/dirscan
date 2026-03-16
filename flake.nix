{
  description = "dirscan - Stateful directory scanning in Python";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python3;

        pythonEnv = python.withPackages (ps: with ps; [
          pytest
          pytest-cov
          hypothesis
          pytest-benchmark
        ]);

        src = pkgs.lib.cleanSource ./.;

        # Helper to create check derivations that need a writable copy of src.
        # Note: tests use /bin/rm (hardcoded in deltree). On macOS this is
        # available in the sandbox; on Linux CI, run with sandbox=relaxed.
        mkPythonCheck = name: script: pkgs.runCommand "check-${name}" {
          nativeBuildInputs = [ pythonEnv pkgs.ruff ];
        } ''
          export HOME=$(mktemp -d)
          cp -r ${src} ./work
          chmod -R +w ./work
          cd ./work
          ${script}
          touch $out
        '';

      in {
        packages.default = pkgs.stdenv.mkDerivation {
          pname = "dirscan";
          version = "2.0.0";
          inherit src;
          buildInputs = [ python ];
          nativeBuildInputs = [ pkgs.makeWrapper ];
          dontBuild = true;
          installPhase = ''
            mkdir -p $out/lib $out/bin
            cp dirscan.py $out/lib/
            makeWrapper ${python}/bin/python3 $out/bin/dirscan \
              --add-flags "$out/lib/dirscan.py"
          '';
        };

        devShells.default = pkgs.mkShell {
          buildInputs = [
            pythonEnv
            pkgs.ruff
            pkgs.lefthook
          ];
        };

        checks = {
          format = mkPythonCheck "format"
            "ruff format --force-exclude --check .";

          lint = mkPythonCheck "lint"
            "ruff check --force-exclude .";

          tests = mkPythonCheck "tests"
            "python -m pytest test_dirscan.py -x -q";

          coverage = mkPythonCheck "coverage"
            "python -m pytest test_dirscan.py --cov=dirscan --cov-report=term-missing --cov-fail-under=30 -q";

          fuzz = mkPythonCheck "fuzz"
            "python -m pytest test_fuzz.py -x -q";

          build = self.packages.${system}.default;
        };
      }
    );
}
