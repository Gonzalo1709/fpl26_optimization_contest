# Development, Test, and Validation Runtime Environment

## Hardware and Software 

Teams are encouraged to develop as much as possible on their own hardware and environments.  However, to provide a fair playing field for testing and validating team submissions, contest organizers have selected the following platform upon which team submissions are evaluated:

AWS Instance [m7a.2xlarge](https://aws.amazon.com/ec2/instance-types/m7a/):
 * 8 vCPUs: 4th Gen AMD EPYC Processors
 * 32 GB RAM

AWS [Vivado ML 2025.1 Developer AMI](https://aws.amazon.com/marketplace/pp/prodview-evssv7ysyt6h4):
 * Ubuntu 22.02 Operating System
 * Pre-installed and licensed Vivado 2025.1

This platform should comfortably run a sequential workflow without any memory pressure issues. A larger platform with more memory and more CPU cores was avoided to enable teams to focus on optimization innovation rather than brute force parallelized exploration.  

At various stages of the contest, teams may be provided with AWS credit to enable them to validate with little or no cost on the contest validation platform.  Successful alpha and beta submissions may enable teams to earn additional credits.  More details to follow.

## LLM Access

If teams will be using LLMs for their workflow (most will), they will be required to use [OpenRouter](https://openrouter.ai/) as demonstrated in the example `dcp_optimizer.py` agent.  OpenRouter is a unified API interface for a wide range of LLMs.  It provides a unified way to switch between many different LLMs using a single API.  Teams may also be provided with OpenRouter credit ahead of submission checkpoints to help develop and validate their solutions.  More details to follow.

Submissions must read from the environment variable `OPENROUTER_API_KEY` for the access key and use the OpenRouter API to access the models.  No other LLM service will be supported. 

## Local checkpoint export and run status

Search snapshots in the run's `admission/` directory include a readable `.edf`
with the same basename as each `.dcp`. Both files are exported from the same
Vivado session. Keep them together when reading a snapshot with RapidWright:
otherwise RapidWright may start an additional Vivado process to regenerate
EDIF, increasing memory use. A missing or empty EDIF export rejects the snapshot.

`published_artifact.json` describes the DCP at the output path. Its
`search_best_candidate` field separately records the best measured candidate's
path, hash, WNS, and validation state as soon as it is admitted. An improvement
is published only after final validation. `run_status` distinguishes a running
search, final validation, completion, failure, and interruption. A retained
fallback alone does not make a failed search successful.

The search deadline preserves the final-validation reserve. Search MCP sessions
are closed in their owning task before the validator starts fresh processes.
An externally cancelled run records its last published output and recoverable
search candidate without labeling pending validation as passed.
