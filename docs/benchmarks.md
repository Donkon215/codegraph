# Scaling benchmarks

Run the complete 1k/10k/100k benchmark locally and save a JSON report:

```powershell
python benchmarks/index_benchmark.py --report benchmark-report.json
```

Use `--quick` for the 1k/10k synthetic-index measurements and a 1k-function
CodeGraph smoke run. The scheduled GitHub Actions workflow runs the complete
suite and uploads its JSON report as an artifact.

The report separates two workloads:

- `benchmarks`: synthetic SQLite indexes with node lookup and callers-query
  latency, indexed edge insert/delete time, index size, and Python allocation
  peak while building the fixture.
- `codegraph_end_to_end`: real temporary Git repositories with 1k, 10k, or
  100k Python functions. Each run times `codegraph build`, changes one source
  file, times `codegraph delta`, records resulting graph node counts, and
  samples the child process's peak resident memory (Linux) or peak working set
  (Windows).

The end-to-end generator writes 100 functions per module. The delta adds one
function to an existing module, so the post-delta graph should contain one more
node than the post-build graph. These timings are observations, not fixed
performance gates; compare reports from the same runner and Python version.

## Local reference run

On Windows 11 with Python 3.12.2, the full script measured:

| Requested functions | Graph nodes after build | Build | Delta | Peak process memory |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 1,010 | 1.44 s | 1.29 s | 41.9 MB |
| 10,000 | 10,100 | 7.79 s | 4.06 s | 97.5 MB |
| 100,000 | 101,000 | 70.63 s | 25.05 s | 634.8 MB |

The separate 100k-node SQLite fixture took 36.50 s to build, used 164.3 MB
peak Python allocation, and occupied 101.3 MB. Node lookup averaged 0.017 ms,
callers lookup 0.019 ms, and indexed edge insert/delete 0.023 ms per edge.
Results vary by machine; the workflow artifact is the authoritative record for
each scheduled run.
