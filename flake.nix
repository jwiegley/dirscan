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
        packages.default = python.pkgs.buildPythonApplication {
          pname = "dirscan";
          version = "2.0.0";
          inherit src;
          format = "other";

          nativeBuildInputs = [ python.pkgs.wrapPython ];

          # Prevent Python from writing .pyc bytecode cache files into the
          # Nix store.  On macOS the store is not mounted read-only, so
          # without this the import of dirscan.py creates __pycache__/
          # inside the store path, silently corrupting its NAR hash and
          # breaking substitution to other machines.
          makeWrapperArgs = [
            "--set" "PYTHONDONTWRITEBYTECODE" "1"
          ];

          installPhase = ''
            runHook preInstall

            # Install dirscan as an importable module in site-packages
            mkdir -p $out/${python.sitePackages}
            cp dirscan.py $out/${python.sitePackages}/

            # Install executable scripts
            mkdir -p $out/bin
            cp cleanup $out/bin/
            cp verify.py $out/bin/verify
            cp share.py $out/bin/share
            cp dirscan.py $out/bin/dirscan

            runHook postInstall
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
