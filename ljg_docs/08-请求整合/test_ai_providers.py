"""Test two AI provider configurations for connectivity"""
import json
import os
import sys
import time

import httpx

sys.stdout.reconfigure(encoding='utf-8')

# Config 1: Zhipu GLM-5.3-Flash
CONFIG_GLM = {
    "AI_PROVIDER": "OPENAI",
    "AI_BASE_URL": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    "AI_API_KEY": "fd82936f373c4af38f481009f2af3d47.C37r9abCD9HUdy8T",
    "AI_MODEL": "glm-5.3-flash",
    "AI_REASONING_EFFORT": "high",
}

# Config 2: Alibaba Bailian Qwen3.8-Flash
CONFIG_QWEN = {
    "AI_PROVIDER": "OPENAI",
    "AI_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "AI_API_KEY": "sk-ws-H.EHDYIPL.cCpm.MEUCIQDt2RlXes4TEuKyFq7tf7-_4-ZXGa0GHcm8juhKZkm39AIgHWVN5OQcRLEkojoY1Et-VMBpJKVN3vSWc21uILbZ4DM",
    "AI_MODEL": "qwen3.8-flash",
    "AI_REASONING_EFFORT": None,
}


def test_provider(name: str, config: dict) -> bool:
    print(f"\n{'='*60}")
    print(f">> Testing: {name}")
    print(f"   Model: {config['AI_MODEL']}")
    print(f"   URL: {config['AI_BASE_URL']}")
    print(f"{'='*60}")

    headers = {
        "Authorization": f"Bearer {config['AI_API_KEY']}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": config["AI_MODEL"],
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful assistant. Answer concisely in Chinese.",
            },
            {
                "role": "user",
                "content": "Please answer in one sentence: What is the capital of China?",
            },
        ],
        "temperature": 0.7,
        "max_tokens": 100,
    }

    # Add reasoning-specific parameters
    if config.get("AI_REASONING_EFFORT"):
        model_lower = config["AI_MODEL"].lower().strip()
        if model_lower.startswith("glm"):
            payload["reasoning_effort"] = config["AI_REASONING_EFFORT"]
            payload["thinking"] = {"type": "enabled", "clear_thinking": False}
        elif model_lower.startswith("qwen"):
            payload["enable_thinking"] = config["AI_REASONING_EFFORT"] in (
                "high", "max", "on", "true"
            )

    endpoint = config["AI_BASE_URL"].rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = endpoint + "/chat/completions"

    extra_params = {k: v for k, v in payload.items() if k not in ('model', 'messages', 'temperature', 'max_tokens')}

    print(f"\n   Endpoint: {endpoint}")
    print(f"   Model: {config['AI_MODEL']}")
    if extra_params:
        print(f"   Extra params: {json.dumps(extra_params, ensure_ascii=False)}")
    print(f"\n   Sending request...")

    started_at = time.perf_counter()

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                endpoint,
                headers=headers,
                json=payload,
            )

        duration_ms = round((time.perf_counter() - started_at) * 1000)

        print(f"   Status: {response.status_code}")
        print(f"   Duration: {duration_ms}ms")

        if response.is_error:
            print(f"   X Error: {response.text[:500]}")
            return False

        response_body = response.json()
        content = response_body["choices"][0]["message"]["content"]
        usage = response_body.get("usage", {})

        print(f"   V Response: {content[:200]}")
        print(f"   Tokens: prompt={usage.get('prompt_tokens', 'N/A')}, "
              f"completion={usage.get('completion_tokens', 'N/A')}")

        if not content or not content.strip():
            print("   X Empty response content")
            return False

        print(f"   V Test PASSED!")
        return True

    except httpx.TimeoutException as e:
        print(f"   X Timeout: {e}")
        return False
    except httpx.RequestError as e:
        print(f"   X Request failed: {e}")
        return False
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"   X Response parse failed: {e}")
        if 'response' in dir():
            print(f"   Raw response: {response.text[:500]}")
        return False
    except Exception as e:
        print(f"   X Unknown error: {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    results = []

    print("=" * 60)
    print("  AI Provider Connectivity Test")
    print("=" * 60)

    # Test GLM
    glm_result = test_provider("Zhipu GLM-5.3-Flash", CONFIG_GLM)
    results.append(("Zhipu GLM-5.3-Flash", glm_result))

    # Test Qwen
    qwen_result = test_provider("Alibaba Qwen3.8-Flash", CONFIG_QWEN)
    results.append(("Alibaba Qwen3.8-Flash", qwen_result))

    # Summary
    print(f"\n{'='*60}")
    print("  Summary")
    print(f"{'='*60}")
    all_pass = True
    for name, result in results:
        status = "V PASS" if result else "X FAIL"
        print(f"  {name}: {status}")
        if not result:
            all_pass = False

    print(f"\n  Overall: {'ALL PASSED V' if all_pass else 'SOME FAILED X'}")
    print(f"{'='*60}")