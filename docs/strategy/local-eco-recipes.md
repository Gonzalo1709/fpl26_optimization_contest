# Local ECO Recipe Policy

Local ECO actions are eligible only when they are tied to evidence from the
target clock, `clk_fpl26contest`. The optimizer keeps the existing generation
branch/checkpoint machinery: each action starts from a saved parent checkpoint,
is rerouted and measured independently, and may replace the incumbent only when
its target-clock result improves the projected contest score.

## Fanout optimization

Fanout candidates are ranked in this order:

1. Number of sampled target-clock critical paths containing the net.
2. Physical span of the net's sinks.
3. Raw sink count.

Clock nets, blacklisted nets, and nets absent from sampled critical paths are
ineligible. RapidWright supplies sink count, bounding-box span, and centroid;
Vivado remains authoritative for timing and routing. The action is bounded to
the top five eligible nets by default.

After RapidWright writes the candidate checkpoint, Vivado reroutes and measures
it. A neutral or worse target-clock result is rejected and the saved parent
checkpoint remains the branch result. An accepted manual netlist change needs
structural validation, and a final submission candidate also needs the 1,000
vector simulation check.

## Path-anchored cell relocation

Relocation candidates come from cells on sampled target-clock critical paths.
RapidWright evaluates the requested placement before mutating the design and
rejects moves farther than `max_move_distance`; the policy default is 30 tile
Manhattan units and the accepted planner range is 5 to 80.

The executor saves a baseline checkpoint and baseline timing report before the
first move. It then performs the existing RapidWright write, Vivado open,
reroute, and target-clock measurement loop. If timing does not improve, the
executor immediately reopens the saved baseline. RapidWright also attempts to
restore the original placement if placing the candidate cell fails.

Relocation is promoted only when its projected contest score is higher than the
parent's. Complete contest validation additionally requires routed/DRC, hold,
pulse-width, structural, and simulation status; unknown fields are never
treated as passes.

## Java recovery for validation

Use `make validate`, which first resolves an existing Java runtime and then the
JRE bundled with Vivado. If RapidWright still reports a missing `libjvm.so` and
no bundled JRE is usable, follow
[`validation-environment.md`](validation-environment.md): install Ubuntu's
`default-jre`, verify `java -version`, and rerun `make validate`. This fallback
is documented for later instances; it was not required on the current instance
because Vivado's bundled JRE worked.
