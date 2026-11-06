# Brief for the agent

Written and committed before the run. The agent gets this file, word for word, as its task.

You are standing in for a PhD student who has been handed a public nf-core pipeline and asked
to run it. You work in an empty workspace directory on a Linux machine with 4 CPUs, 15 GB of
memory, Java 21 and a running Docker daemon. Nothing else is installed for you.

## The job

1. **Set up.** Get Nextflow working in the workspace. The pipeline is nf-core/rnaseq release
   `3.27.0`, which needs Nextflow 25.10.4 or later. Use Docker for software (`-profile docker`).
2. **Validation run.** Run the pipeline's own test profile once, unchanged:
   `-profile test,docker`, with the run name `validation`.
3. **Sample batch.** Run the pipeline once per sample, so each sample gets its own run, its own
   output folder and its own report. The samples are the five in the test profile's samplesheet
   (`https://raw.githubusercontent.com/nf-core/test-datasets/626c8fab639062eade4b10747e919341cbf9b41a/samplesheet/v3.10/samplesheet_test.csv`;
   some samples have more than one row, keep those rows together), plus one more sample a
   collaborator sent, whose samplesheet is `inputs/collab_samplesheet.csv` in the workspace.
   Keep the test profile for everything else (references and settings), so each batch run is
   `-profile test,docker --input <that sample's samplesheet>`. Name the runs `sample_<SAMPLE>`.
4. **Retry failures.** When a run fails, find out why from its logs. If it is something
   transient or environmental, retry it with `-resume`. Retry any run at most twice.
5. **Summarize.** When every run has finished or used its retries, return the run report: for
   each run, whether it finished, how many attempts it took, its wall-clock time, and for any
   failure the cause and what fixed it (or that nothing did).

## Rules

- **A person approves every change to the pipeline or its parameters.** The only parameters you
  may set without asking are `--input` and `--outdir`, plus Nextflow's own `-profile test,docker`,
  `-resume`, `-name` and `-w`. Anything else (another `--param`, a `-c` config, a process
  resource change, editing pipeline code) must go through `request_approval` first, with the
  exact arguments and why. If the person says no, don't do it.
- Don't change, fix or replace input data. If a sample's input is bad, report it.
- Stay out of the science: no choice of methods and no interpretation of results.
- Run one pipeline at a time; the machine is small.
- Use the `launch_run` tool to start pipeline runs, not the shell.
- Spending cap: $2.00 of model calls. The harness stops you at the cap.
