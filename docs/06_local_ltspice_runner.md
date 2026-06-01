# Local LTspice runner

## Principle

LTspice must be installed by the user. The application does not provide LTspice and does not run it as a shared server service.

## Operating modes

### `dry-run` mode

- generate the netlist,
- generate the command,
- do not invoke LTspice,
- report what would need to be run.

### `local-run` mode

- detect LTspice,
- run batch mode,
- collect `.log` and `.raw`,
- save under `results/`.

## Configuration

Example:

```yaml
ltspice:
  executable_path: "C:/Program Files/ADI/LTspice/LTspice.exe"
  mode: "local-run"
  timeout_seconds: 120
  allow_network: false
```

## Error handling

- LTspice missing: diagnostic report and instructions for setting the path,
- libraries missing: list of missing `.include`s,
- simulation error: save the `.log`,
- timeout: terminate the process,
- `.raw` missing: warning and `.log`-only analysis.

## License guardrails

- Do not include LTspice in the installer.
- Do not upload the schematic to a server in order to run LTspice.
- Do not imply an official integration with Analog Devices.
- The user is responsible for their own LTspice installation and license.
