#!/usr/bin/env python3
import os
import json
import re
import urllib.parse
import argparse

def find_metadata_files(root):
  for dirpath, _, filenames in os.walk(root):
    if "metadata.json" in filenames:
      yield os.path.join(dirpath, "metadata.json")

def make_model_url(recompiled_dir, folder, file_name):
  # Updated to use GitHub raw content URL for hoofpilot/models repository
  base = f"https://raw.githubusercontent.com/hoofpilot/models/master/recompiled/{recompiled_dir}/"
  safe_folder = urllib.parse.quote(folder)
  safe_file = urllib.parse.quote(file_name)
  return f"{base}{safe_folder}/{safe_file}"

def update_bundle_models(bundle, meta_models, folder, recompiled_dir):
  filtered_meta_models = [
    m for m in meta_models
    if "big" not in m["artifact"]["file_name"].lower()
    and "big" not in m["metadata"]["file_name"].lower()
  ]
  for model in bundle.get("models", []):
    meta_model = next((m for m in filtered_meta_models if m["type"] == model["type"]), None)
    if not meta_model:
      continue
    model["artifact"]["file_name"] = meta_model["artifact"]["file_name"]
    model["artifact"]["download_uri"]["sha256"] = meta_model["artifact"]["download_uri"]["sha256"]
    model["artifact"]["download_uri"]["url"] = make_model_url(recompiled_dir, folder, meta_model["artifact"]["file_name"])
    model["metadata"]["file_name"] = meta_model["metadata"]["file_name"]
    model["metadata"]["download_uri"]["sha256"] = meta_model["metadata"]["download_uri"]["sha256"]
    model["metadata"]["download_uri"]["url"] = make_model_url(recompiled_dir, folder, meta_model["metadata"]["file_name"])

def collapse_overrides(json_text):
  def replacer(m):
    items = [line.strip().rstrip(',') for line in m.group(2).splitlines() if line.strip()]
    return f'{m.group(1)}{{ {", ".join(items)} }}'
  return re.sub(
    r'("overrides": ){\s*([^}]*)\s*}',
    replacer,
    json_text
  )

def get_generation_and_selector(short_name, bundles):
  prefix = re.match(r"([A-Za-z]+)", short_name)
  prefix = prefix.group(1) if prefix else short_name
  candidates = [b for b in bundles if b["short_name"].startswith(prefix) and "generation" in b and "minimum_selector_version" in b]
  if candidates:
    latest = max(candidates, key=lambda b: b.get("index", 0))
    return latest["generation"], latest["minimum_selector_version"]
  # Fallback
  return "12", "12"

def extract_date_from_display_name(display_name):
  date = re.search(r'\(([^)]+)\)', display_name)
  if not date:
    return ""
  return date.group(1)

def parse_date(date_str):
  # Try to parse "Month Day, Year" to a sortable tuple (year, month, day)
  import datetime
  try:
    return datetime.datetime.strptime(date_str, "%B %d, %Y")
  except Exception:
    return datetime.datetime.min

def main():
  parser = argparse.ArgumentParser(description="Update driving_models JSON with new recompiled models")
  parser.add_argument("--json-path", required=True, help="Path to driving_models_vX.json")
  parser.add_argument("--recompiled-dir", required=True, help="Path to recompiledX directory")
  parser.add_argument("--model-folder", required=False, help="Folder name for new model (overrides auto-detect)")
  parser.add_argument("--lat", required=False, type=str, default=".0", help="Lat smooth (decimal, e.g. 0.1)")
  parser.add_argument("--long", required=False, type=str, default=".3", help="long smooth (decimal, e.g. 0.3)")
  parser.add_argument("--generation", required=False, type=str, default=None, help="Model generation")
  parser.add_argument("--version", required=False, type=str, default=None, help="Minimum selector version")
  parser.add_argument("--set-min-version", required=False, type=str, default=None, help="Set minimum selector version for all tinygrad models")
  parser.add_argument("--sort-by-date", required=False, action="store_true", help="Sort bundles by date in display_name")
  parser.add_argument("--tinygrad-ref", required=False, type=str, default=None, help="Set tinygrad_ref top-level key in json")
  args = parser.parse_args()
  recompiled_dir_name = os.path.basename(os.path.normpath(args.recompiled_dir))

  with open(args.json_path, "r", encoding="utf-8") as f:
    driving_models_json = json.load(f)

  if args.tinygrad_ref is not None:
    driving_models_json["tinygrad_ref"] = args.tinygrad_ref

  ref_to_bundle = {bundle["ref"]: bundle for bundle in driving_models_json["bundles"]}

  for meta_path in find_metadata_files(args.recompiled_dir):
    with open(meta_path, "r", encoding="utf-8") as f:
      meta = json.load(f)
    ref = meta["ref"]
    folder = os.path.basename(os.path.dirname(meta_path))
    short_name = meta.get("short_name", folder).upper()

    if ref not in ref_to_bundle:
      print(f"Adding new bundle for ref: {ref}")
      folder_key = args.model_folder or f"{short_name.split()[0].upper()} Models"
      index = max([bundle.get("index", 0) for bundle in driving_models_json["bundles"] if isinstance(bundle.get("index", 0), int)], default=0) + 1
      fallback_generation, fallback_version = get_generation_and_selector(short_name, driving_models_json["bundles"])
      generation = args.generation if args.generation is not None else fallback_generation
      version = args.version if args.version is not None else fallback_version

      filtered_models = [
        m for m in meta["models"]
        if "big" not in m["artifact"]["file_name"].lower()
        and "big" not in m["metadata"]["file_name"].lower()
      ]
      new_bundle = {
        "short_name": short_name,
        "display_name": meta.get("display_name", short_name),
        "is_20hz": meta.get("is_20hz", False),
        "ref": ref,
        "environment": "development",
        "runner": "tinygrad",
        "index": index,
        "minimum_selector_version": version,
        "generation": generation,
        "build_time": meta.get("build_time"),
        "overrides": {"folder": folder_key, "lat": args.lat, "long": args.long},
        "models": filtered_models
      }
      driving_models_json["bundles"].append(new_bundle)
      ref_to_bundle[ref] = new_bundle

    bundle = ref_to_bundle[ref]
    bundle["short_name"] = bundle["short_name"].upper()
    update_bundle_models(bundle, meta["models"], folder, recompiled_dir_name)
    bundle["display_name"] = meta.get("display_name", bundle["display_name"])
    bundle["is_20hz"] = meta.get("is_20hz", bundle["is_20hz"])
    bundle["build_time"] = meta.get("build_time", bundle.get("build_time"))
    print(f"Updated bundle for ref: {ref}")

  if args.set_min_version is not None:
    for bundle in driving_models_json["bundles"]:
      bundle["minimum_selector_version"] = args.set_min_version

  if args.sort_by_date:
    def bundle_sort_key(bundle):
      date_str = extract_date_from_display_name(bundle.get("display_name", ""))
      return parse_date(date_str)
    driving_models_json["bundles"].sort(key=bundle_sort_key)
    # After sorting, arrange indexes from 0
    for idx, bundle in enumerate(driving_models_json["bundles"], 0):
      bundle["index"] = idx

  with open(args.json_path, "w", encoding="utf-8") as f:
    json_text = json.dumps(driving_models_json, indent=2)
    json_text = collapse_overrides(json_text)
    f.write(json_text)
    f.write('\n')
  print(f"{os.path.basename(args.json_path)} updated.")

if __name__ == "__main__":
  main()

