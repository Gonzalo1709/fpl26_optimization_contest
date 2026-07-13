# Validation Runtime Environment

`make validate` is the supported equivalence-check entrypoint. It exports the
repository-local RapidWright paths and `VIVADO_EXEC`, then
`validate_dcps.py` builds the RapidWright MCP subprocess environment using the
same helper as the optimizer.

## Java resolution order

The helper resolves Java in this order:

1. `JAVA_HOME`, when explicitly configured.
2. `java` found on `PATH`, resolving symlinks before deriving its home.
3. The JRE bundled under the Vivado installation selected by `VIVADO_EXEC`.
4. The bundled JRE under `vivado` found on `PATH`.

If none is available, validation stops before launching the MCP server and
reports how to configure the runtime. The chosen Java `bin` directory is
prepended to the subprocess `PATH`.

## Ubuntu fallback

If RapidWright reports that `libjvm.so` cannot be found and neither an existing
`JAVA_HOME` nor Vivado's bundled JRE is usable, install the distribution Java
runtime and retry:

```bash
sudo apt update
sudo apt install default-jre
java -version
make validate GOLDEN=golden.dcp REVISED=revised.dcp VECTORS=1000
```

On the contest instance, first try the bundled Vivado JRE because it is already
present and avoids changing the machine. Use `default-jre` only when the
resolver's error or the RapidWright log confirms Java is still unavailable.

The subprocess also receives:

- `RAPIDWRIGHT_PATH=<repo>/RapidWright`
- `CLASSPATH=<repo>/RapidWright/bin:<repo>/RapidWright/jars/*` on Linux

## Contest-instance command

```bash
source /tools/Xilinx/2025.1/Vivado/settings64.sh
make validate \
  GOLDEN=/absolute/path/to/golden.dcp \
  REVISED=/absolute/path/to/revised.dcp \
  VECTORS=1000 \
  VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado
```

Use the same DCP for `GOLDEN` and `REVISED` as an environment smoke test. A
real optimized result must be checked against its original benchmark DCP.

## Final Vivado legality check

After equivalence validation, run the repository legality script on the exact
candidate DCP:

```bash
vivado -mode batch -notrace \
  -log legality.log -journal legality.jou \
  -source scripts/check_dcp_legality.tcl \
  -tclargs revised.dcp
```

The script checks non-virtual primitive placement, complete route status,
error-severity DRCs, worst hold slack, and pulse-width violators. VCC/GND
pseudo-cells are excluded from the placement count; they do not require LOCs.

Direct invocation is also supported after setting `VIVADO_EXEC` or making
Vivado discoverable on `PATH`:

```bash
export VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado
python3 validate_dcps.py golden.dcp revised.dcp --vectors 1000
```
