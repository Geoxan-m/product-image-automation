"""Batch product-image preparation. Originals are never modified."""
from pathlib import Path
from io import BytesIO
import argparse
import hashlib
import json
import os
import sys

from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

WIDTH, HEIGHT, MARGIN, MAX_KB = 600, 399, 12, 250
EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff',
              '.gif', '.avif', '.heic', '.heif'}
OUTPUT_FOLDER = 'Fixed images'
MANIFEST_NAME = '.processed-images.json'


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path, data):
    temporary = path.with_name(path.name + '.tmp')
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def find_images(root):
    result = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories
                          if name.casefold() != OUTPUT_FOLDER.casefold()
                          and not (Path(current) / name).is_symlink()]
        for name in filenames:
            path = Path(current) / name
            if not path.is_symlink() and path.suffix.lower() in EXTENSIONS:
                result.append(path)
    return sorted(result, key=lambda p: p.relative_to(root).as_posix().casefold())


def prepare_image(path, session, remove_background):
    with Image.open(path) as source:
        source.seek(0)  # First frame only for animated/multipage files.
        image = ImageOps.exif_transpose(source).convert('RGBA')
    if remove_background:
        from rembg import remove
        image = remove(image, session=session).convert('RGBA')
    alpha = image.getchannel('A')
    visible = alpha.point(lambda value: 255 if value > 20 else 0)
    bounds = visible.getbbox()
    if bounds is None:
        raise ValueError('No visible product found after background removal.')
    image = ImageOps.contain(image.crop(bounds),
                             (WIDTH - 2 * MARGIN, HEIGHT - 2 * MARGIN),
                             method=Image.Resampling.LANCZOS)
    canvas = Image.new('RGB', (WIDTH, HEIGHT), 'white')
    position = ((WIDTH - image.width) // 2, (HEIGHT - image.height) // 2)
    canvas.paste(image, position, image.getchannel('A'))
    return canvas


def optimized_jpeg(image):
    for quality in (95, 92, 90, 87, 85, 82, 80, 75, 70, 65):
        buffer = BytesIO()
        image.save(buffer, format='JPEG', quality=quality,
                   optimize=True, progressive=True)
        data = buffer.getvalue()
        if len(data) <= MAX_KB * 1024:
            return data, quality
    return data, quality


def main():
    parser = argparse.ArgumentParser(
        description='Prepare product images as centred 600x399 JPGs.')
    parser.add_argument('folder', help='Folder containing your original images')
    parser.add_argument('--keep-background', action='store_true',
                        help='Skip AI removal; retain the original background.')
    args = parser.parse_args()
    root = Path(args.folder).expanduser().resolve()
    if not root.is_dir():
        parser.error('The selected folder does not exist.')
    if root.name.casefold() == OUTPUT_FOLDER.casefold():
        parser.error("Choose the ORIGINAL folder, not 'Fixed images'.")
    files = find_images(root)
    if not files:
        print('No supported images found. Nothing to do.')
        return 0
    output = root / OUTPUT_FOLDER
    if output.is_symlink():
        parser.error("'Fixed images' must not be a directory link.")
    output.mkdir(exist_ok=True)
    manifest_path = output / MANIFEST_NAME
    try:
        manifest = (json.loads(manifest_path.read_text(encoding='utf-8'))
                    if manifest_path.exists() else {})
        if not isinstance(manifest, dict):
            raise ValueError('Invalid processing history.')
    except (ValueError, OSError) as exc:
        print(f'Cannot read processing history: {exc}')
        print('Stopped to avoid creating duplicate outputs.')
        return 1
    settings = dict(version=1, width=WIDTH, height=HEIGHT, margin=MARGIN,
                    max_kb=MAX_KB, remove_background=not args.keep_background,
                    model='u2net')
    targets, reserved = {}, set()
    for source in files:
        relative = source.relative_to(root)
        target = relative.with_suffix('.jpg')
        key = target.as_posix().casefold()
        if key in reserved:
            suffix = hashlib.sha256(relative.as_posix().encode('utf-8')).hexdigest()[:10]
            target = relative.with_name(f'{relative.stem}__{suffix}.jpg')
            key = target.as_posix().casefold()
        reserved.add(key)
        targets[source] = target
    session = None
    saved = skipped = errors = 0
    lock_path = output / '.processing.lock'
    try:
        lock = lock_path.open('x', encoding='utf-8')
    except FileExistsError:
        print('Another run may already be processing this folder.')
        print('If an earlier run crashed, remove .processing.lock and retry.')
        return 1
    try:
        lock.write(str(os.getpid()))
        lock.close()
        print(f'Found {len(files)} images.\nOutput: {output}')
        print('Original files will remain unchanged.\n')
        for index, source in enumerate(files, start=1):
            relative = source.relative_to(root).as_posix()
            try:
                digest = sha256_file(source)
                previous = manifest.get(relative)
                target_relative = (previous['output']
                                    if isinstance(previous, dict) and 'output' in previous
                                    else targets[source].as_posix())
                target = (output / target_relative).resolve()
                if not target.is_relative_to(output.resolve()):
                    raise ValueError('Invalid output path in processing history.')
                if target.exists():
                    managed = (isinstance(previous, dict)
                               and previous.get('output_sha256') == sha256_file(target))
                    if not managed:
                        skipped += 1
                        print(f'[{index}/{len(files)}] SKIP existing: {relative}')
                        continue
                    if (previous.get('source_sha256') == digest
                            and previous.get('settings') == settings):
                        skipped += 1
                        print(f'[{index}/{len(files)}] SKIP completed: {relative}')
                        continue
                if not args.keep_background and session is None:
                    print('Loading background-removal model. First use may download it...')
                    from rembg import new_session
                    session = new_session('u2net')
                image = prepare_image(source, session, not args.keep_background)
                data, quality = optimized_jpeg(image)
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(target, data)
                manifest[relative] = dict(
                    source_sha256=digest,
                    output=target.relative_to(output).as_posix(),
                    output_sha256=hashlib.sha256(data).hexdigest(), settings=settings)
                atomic_write(manifest_path,
                             json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))
                saved += 1
                size_kb = len(data) / 1024
                print(f'[{index}/{len(files)}] SAVED #{saved}: {relative}'
                      f' -> {target.name} | {size_kb:.1f} KB | JPEG quality {quality}')
                if size_kb > MAX_KB:
                    print(f'  NOTE: Above the {MAX_KB} KB size target.')
            except Exception as exc:
                errors += 1
                print(f'[{index}/{len(files)}] ERROR: {relative}: {exc}')
        print('\n' + '=' * 48)
        print(f'Images found: {len(files)}\nJPGs saved this run: {saved}')
        print(f'Already processed / kept: {skipped}\nErrors: {errors}\nSaved in: {output}')
        return 1 if errors else 0
    finally:
        lock.close()
        lock_path.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\nStopped. Run again to resume remaining images.')
        sys.exit(130)
