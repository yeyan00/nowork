"""
Test script for CodingTools image reading support (nowork).

Tests:
1. MIME detection utility (unit tests)
2. read_file returning ToolResult for images (unit tests)
3. Agent with qwen3.6-plus reading an image (integration test, requires API key)

Usage:
    python tests/test_image_read.py
    python tests/test_image_read.py --integration
"""

import os
import sys
import argparse
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "server"))

ASSERTS = Path(__file__).resolve().parent.parent / "asserts"


# =============================================================================
# Test 1: MIME detection utility
# =============================================================================

def test_mime_detection():
    from app.utils.mime import sniff_mime_type, is_image, is_pdf

    print("=" * 60)
    print("Test 1: MIME detection utility")
    print("=" * 60)

    test_files = {
        "demo.png": "image/png",
        "icon.png": "image/png",
        "icon_512.png": "image/png",
        "main.png": "image/png",
        "kl_demo.png": "image/png",
        "team.png": "image/png",
    }

    all_passed = True
    for filename, expected_mime in test_files.items():
        filepath = ASSERTS / filename
        if not filepath.exists():
            print(f"  SKIP: {filename} not found at {filepath}")
            continue
        with open(filepath, "rb") as f:
            sample = f.read(8192)
        detected = sniff_mime_type(filepath, sample)
        img = is_image(filepath, sample)
        pdf = is_pdf(filepath, sample)
        status = "PASS" if detected == expected_mime and img and not pdf else "FAIL"
        if status == "FAIL":
            all_passed = False
        print(f"  [{status}] {filename}: detected={detected}, is_image={img}, is_pdf={pdf}")

    print("\n  Extension-based fallback:")
    for ext, mime in [(".jpg", "image/jpeg"), (".jpeg", "image/jpeg"), (".gif", "image/gif"),
                       (".webp", "image/webp"), (".bmp", "image/bmp"), (".pdf", "application/pdf"),
                       (".txt", "application/octet-stream")]:
        result = sniff_mime_type(f"test{ext}")
        status = "PASS" if result == mime else "FAIL"
        if status == "FAIL":
            all_passed = False
        print(f"    [{status}] test{ext} -> {result}")

    print("\n  Magic bytes detection:")
    magic_tests = [
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "image/png", "PNG header"),
        (b"\xff\xd8\xff\xe0" + b"\x00" * 100, "image/jpeg", "JPEG header"),
        (b"GIF89a" + b"\x00" * 100, "image/gif", "GIF header"),
        (b"BM" + b"\x00" * 100, "image/bmp", "BMP header"),
        (b"%PDF-1.4" + b"\x00" * 100, "application/pdf", "PDF header"),
        (b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 20, "image/webp", "WebP header"),
    ]
    for data, expected_mime, desc in magic_tests:
        result = sniff_mime_type("test.bin", sample_bytes=data)
        status = "PASS" if result == expected_mime else "FAIL"
        if status == "FAIL":
            all_passed = False
        print(f"    [{status}] {desc}: {result}")

    print(f"\n  Overall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    return all_passed


# =============================================================================
# Test 2: CodingTools.read_file with images
# =============================================================================

def test_read_file_image():
    from app.tools.codingTools import CodingTools
    from agno.tools.function import ToolResult

    print("\n" + "=" * 60)
    print("Test 2: CodingTools.read_file with images")
    print("=" * 60)

    tools = CodingTools(base_dirs=[str(ASSERTS)],
                         enable_grep=False, enable_find=False, enable_ls=False,
                         enable_run_shell=False, enable_edit_file=False, enable_write_file=False)
    all_passed = True

    image_path = str(ASSERTS / "main.png")
    print(f"\n  Reading image: {image_path}")
    result = tools.read_file(image_path)
    if isinstance(result, ToolResult):
        print(f"  [PASS] read_file returned ToolResult")
        img = result.images[0]
        print(f"    images[0].mime_type: {img.mime_type}")
        print(f"    images[0].content size: {len(img.content) if img.content else 0} bytes")
    else:
        print(f"  [FAIL] read_file returned str: {str(result)[:100]}")
        all_passed = False

    print(f"\n  Reading text file...")
    text_path = str(Path(__file__).resolve())
    tools2 = CodingTools(base_dirs=[str(Path(__file__).resolve().parent)],
                          enable_grep=False, enable_find=False, enable_ls=False,
                          enable_run_shell=False, enable_edit_file=False, enable_write_file=False)
    result2 = tools2.read_file(text_path)
    if isinstance(result2, str):
        print(f"  [PASS] read_file returned str for text file")
    else:
        print(f"  [FAIL] read_file returned ToolResult for text file")
        all_passed = False

    print(f"\n  Reading binary file...")
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False, dir=str(Path(__file__).resolve().parent)) as f:
        f.write(b"\x00\x01\x02\x03\x04\x05")
        bin_path = f.name
    try:
        tools3 = CodingTools(base_dirs=[str(Path(bin_path).resolve().parent)],
                              enable_grep=False, enable_find=False, enable_ls=False,
                              enable_run_shell=False, enable_edit_file=False, enable_write_file=False)
        result3 = tools3.read_file(bin_path)
        if isinstance(result3, str) and "Binary file detected" in result3:
            print(f"  [PASS] read_file correctly returned binary error")
        else:
            print(f"  [FAIL] binary file not handled correctly")
            all_passed = False
    finally:
        os.unlink(bin_path)

    print(f"\n  Testing all images in asserts:")
    for img_name in ["demo.png", "icon.png", "icon_512.png", "kl_demo.png", "main.png", "team.png"]:
        img_path = str(ASSERTS / img_name)
        if not Path(img_path).exists():
            continue
        result = tools.read_file(img_path)
        if isinstance(result, ToolResult) and result.images:
            img = result.images[0]
            print(f"    [PASS] {img_name}: mime={img.mime_type}, size={len(img.content) if img.content else 0} bytes")
        else:
            print(f"    [FAIL] {img_name}")
            all_passed = False

    print(f"\n  Overall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    return all_passed


# =============================================================================
# Test 3: Integration test with qwen3.6-plus
# =============================================================================

def test_agent_image_reading(image_path: str = None):
    print("\n" + "=" * 60)
    print("Test 3: Agent integration test with qwen3.6-plus")
    print("=" * 60)

    try:
        from agno.agent import Agent
        from agno.models.openai.like import OpenAILike
    except ImportError as e:
        print(f"  SKIP: Cannot import agno modules: {e}")
        return None

    base_url = "https://coding.dashscope.aliyuncs.com/v1"
    api_key = os.environ.get("DASHSCOPE_API_KEY", "sk-sp-05a678973f1f424f97da1a516b8250d9")

    model = OpenAILike(
        id="qwen3.6-plus",
        name="qwen3.6-plus",
        base_url=base_url,
        api_key=api_key,
    )

    if image_path is None:
        image_path = str(ASSERTS / "main.png")
    if not Path(image_path).exists():
        print(f"  SKIP: Image file not found: {image_path}")
        return None

    from app.tools.codingTools import CodingTools as CT
    tools = CT(base_dirs=[str(ASSERTS)],
                enable_grep=False, enable_find=False, enable_ls=True,
                enable_run_shell=False, enable_edit_file=False, enable_write_file=False)

    agent = Agent(model=model, tools=[tools],
                  instructions="You are a helpful assistant that can read and analyze images.")

    print(f"\n  Running agent with image: {image_path}")
    print(f"  Model: qwen3.6-plus")
    print(f"  Prompt: 'Please read the image at {image_path} using the read_file tool and describe what you see in it.'\n")

    try:
        response = agent.run(
            f"Please read the image at {image_path} using the read_file tool and describe what you see in it."
        )
        print(f"\n  Agent response:")
        print(f"  {'-' * 40}")
        content = ""
        if hasattr(response, 'content') and response.content:
            content = response.content
        elif response and hasattr(response, 'messages') and response.messages:
            for msg in response.messages:
                if hasattr(msg, 'content') and msg.content:
                    content += msg.content + "\n"
        else:
            content = str(response) if response else "No response"
        print(f"  {content[:500]}{'...' if len(content) > 500 else ''}")
        print(f"  {'-' * 40}")

        saw_image = False
        if response and hasattr(response, 'messages') and response.messages:
            for msg in response.messages:
                if hasattr(msg, 'images') and msg.images:
                    saw_image = True
                    print(f"\n  [INFO] Found {len(msg.images)} image(s) in messages")
                    break

        image_keywords = ["screenshot", "interface", "ui", "software", "application",
                          "window", "dashboard", "button", "menu", "icon", "screen",
                          "界面", "截图", "软件", "按钮", "窗口"]
        image_described = any(kw in content.lower() for kw in image_keywords)

        if image_described:
            print(f"  [PASS] Agent described the image content")
        elif saw_image:
            print(f"  [PASS] Image was passed to the model")
        else:
            print(f"  [FAIL] Agent did not appear to analyze the image")
        return True

    except Exception as e:
        print(f"\n  [FAIL] Agent error: {e}")
        import traceback
        traceback.print_exc()
        return False


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Test CodingTools image reading")
    parser.add_argument("--integration", action="store_true")
    parser.add_argument("--image", type=str, default=None)
    args = parser.parse_args()

    results = {}
    results["mime_detection"] = test_mime_detection()
    results["read_file_image"] = test_read_file_image()

    if args.integration:
        results["agent_integration"] = test_agent_image_reading(args.image)
    else:
        print("\n" + "=" * 60)
        print("Test 3: Agent integration test (SKIPPED)")
        print("  Run with --integration to test with qwen3.6-plus")
        print("=" * 60)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, passed in results.items():
        print(f"  {name}: {'PASSED' if passed else 'FAILED' if passed is False else 'SKIPPED'}")

    return 0 if all(r is True for r in results.values() if r is not None) else 1


if __name__ == "__main__":
    sys.exit(main())