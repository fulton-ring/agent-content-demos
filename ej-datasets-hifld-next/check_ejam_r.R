# Runs EJAM's own pctile_from_raw_lookup() on the inputs the notebook writes, so the
# notebook can compare its Python port with the R original. Needs only base R.
# Usage: Rscript check_ejam_r.R <pctile_from_raw_lookup.R> <values.csv> <usastats.csv>
#          <statestats.csv> <comma-separated columns> <output.csv>
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 6)
source(args[1])
bg <- read.csv(args[2], stringsAsFactors = FALSE, colClasses = c(ID = "character"))
us <- read.csv(args[3], stringsAsFactors = FALSE, check.names = FALSE)
st <- read.csv(args[4], stringsAsFactors = FALSE, check.names = FALSE)
out <- data.frame(ID = bg$ID)
for (v in strsplit(args[5], ",")[[1]]) {
  values <- bg[[make.names(v)]]
  out[[paste0("us_", v)]] <- suppressWarnings(pctile_from_raw_lookup(values, v, us, "USA"))
  out[[paste0("st_", v)]] <- suppressWarnings(pctile_from_raw_lookup(values, v, st, bg$ST))
}
write.csv(out, args[6], row.names = FALSE)
