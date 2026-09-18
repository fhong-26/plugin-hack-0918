"""Small real Transformer tests verify training, caching and adapter isolation."""
from types import SimpleNamespace
import pytest


def test_frozen_prefix_training_matches_full_forward_and_updates_only_adapters(tmp_path):
    torch = pytest.importorskip("torch")
    from transformers import Qwen3Config, Qwen3ForCausalLM
    from peft import LoraConfig, get_peft_model
    torch.manual_seed(13)
    model = Qwen3ForCausalLM(Qwen3Config(vocab_size=64, hidden_size=32, intermediate_size=64,
        num_hidden_layers=3, num_attention_heads=2, num_key_value_heads=1, head_dim=16))
    model.eval()
    ids = torch.tensor([[1, 4, 8, 12, 16]])
    capture = []
    hook = model.model.layers[2].register_forward_pre_hook(lambda m, a, kw: capture.append(
        (a[0] if a else kw["hidden_states"]).detach().clone()), with_kwargs=True)
    with torch.no_grad():
        initial = model(ids, use_cache=False, logits_to_keep=1).logits
    hook.remove()
    model = get_peft_model(model, LoraConfig(r=2, lora_alpha=4, lora_dropout=0,
        target_modules=["q_proj", "v_proj"], layers_to_transform=[2], task_type="CAUSAL_LM"))
    base = model.get_base_model()
    frozen = {n: p.detach().clone() for n, p in model.named_parameters() if not p.requires_grad}
    full_layers = base.model.layers
    base.model.layers = torch.nn.ModuleList([full_layers[2]])
    try:
        truncated = model(inputs_embeds=capture[0], use_cache=False, logits_to_keep=1).logits
        assert torch.allclose(initial, truncated, atol=1e-6)
        loss = torch.nn.functional.cross_entropy(truncated[0, -1, [2, 3, 4]][None], torch.tensor([1]))
        loss.backward()
    finally:
        base.model.layers = full_layers
    trainable = [p for p in model.parameters() if p.requires_grad]
    assert any(p.grad is not None and p.grad.abs().sum() > 0 for p in trainable)
    optimizer = torch.optim.AdamW(trainable, lr=0.01)
    optimizer.step()
    assert all(torch.equal(frozen[n], p) for n, p in model.named_parameters() if n in frozen)
    with torch.no_grad():
        after = model(ids, use_cache=False, logits_to_keep=1).logits
    assert not torch.allclose(initial, after)
    model = model.unload()
    with torch.no_grad():
        restored = model(ids, use_cache=False, logits_to_keep=1).logits
    assert torch.allclose(initial, restored, atol=1e-6)
