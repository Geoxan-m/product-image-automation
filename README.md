# Product Image Automation

Batch product-photo preparation with Python, designed for a Windows PowerShell workflow. Created by Georgios Xanthakis with AI assistance, based on a real workplace need to prepare catalogue and web images to consistent e-commerce specifications.

## Features

- Recursively processes image folders, skipping empty folders and all `Fixed images` folders.
- Removes backgrounds using rembg and places the product on white.
- Fits and centres the product at **600 × 399 px**, preserving its aspect ratio.
- Converts supported formats to optimized JPG, with a **250 KB target**.
- Keeps originals unchanged and preserves relative folder structure and filenames.
- Uses a processing-history file to skip completed work and resume after interruptions.
- Handles duplicate filename stems, reports individual errors and prints progress and final totals.
- Supports an optional mode that keeps the original background.

## Windows setup

Install a Python version supported by rembg (Python 3.11 or 3.12 is a practical starting point), then open PowerShell in this project's folder:

```powershell
py -m pip install -r requirements.txt
py .\fix_images.py "$env:USERPROFILE\Desktop\Products"
```

Replace `Products` with the folder holding your originals. You do not need to create an output folder. The script creates `Products\Fixed images` automatically.

```text
Products/
  photo.png
  Category/photo.webp
  Fixed images/
    photo.jpg
    Category/photo.jpg
    .processed-images.json
```

To skip AI background removal:

```powershell
py .\fix_images.py "$env:USERPROFILE\Desktop\Products" --keep-background
```

The first background-removal run downloads the U2Net model. Later runs reuse the locally cached model. Processing is local; this script does not upload product photos to an API.

## Processing history

`.processed-images.json` records input hashes, output filenames, output hashes and settings. Leave it in the output folder. It is not an image and should not be uploaded to the e-shop. Files edited outside the script are kept rather than overwritten. Changed source files or settings regenerate outputs owned by the script; unchanged completed files are skipped.

A `.processing.lock` file prevents simultaneous runs. If the process was forcibly terminated, confirm no run is active before removing a stale lock file.

## Limits

Background removal is probabilistic: review white, transparent, reflective or intricate products manually. Upscaling cannot restore missing detail, and JPEG compression is lossy. The size target is best-effort; larger outputs produce a warning rather than lowering quality indefinitely. Cropping trims transparent space around the detected product, not the product to fill the frame. Animated GIFs and multipage TIFFs use their first frame only. HEIC/HEIF and AVIF decoding depends on installed decoder support.

## Validation

The workflow was tried by the author on Windows. The included automated tests cover the deterministic conversion path, folder traversal, originals preservation, rerun skipping, corrupt-file handling and filename collisions. AI cutout quality still needs visual review for each product category.

```powershell
py -m unittest discover -s tests -v
```

## Development

AI-assisted implementation based on requirements and practical use directed by Georgios Xanthakis. No employer images, customer information, processing manifests or model weights are included in this repository.

References: [Pillow](https://pillow.readthedocs.io/) · [rembg](https://github.com/danielgatis/rembg) · [pillow-heif](https://github.com/bigcat88/pillow_heif)
