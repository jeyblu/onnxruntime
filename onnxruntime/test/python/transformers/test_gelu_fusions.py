import math
import os
import unittest

import torch
from parameterized import parameterized
from parity_utilities import find_transformers_source

if find_transformers_source():
    from optimizer import optimize_model
else:
    from onnxruntime.transformers.optimizer import optimize_model


class HuggingfaceGelu(torch.nn.Module):
    def forward(self, x):
        return x * 0.5 * (1.0 + torch.erf(x / math.sqrt(2.0)))


class HuggingfaceFastGelu(torch.nn.Module):
    def forward(self, x):
        return 0.5 * x * (1.0 + torch.tanh(x * 0.7978845608 * (1.0 + 0.044715 * x * x)))


class HuggingfaceQuickGelu(torch.nn.Module):
    def forward(self, x):
        return x * torch.sigmoid(1.702 * x)


class HuggingfaceTorchGeluTanh(torch.nn.Module):
    def forward(self, x):
        return torch.nn.functional.gelu(x, approximate="tanh")


class MegatronGelu(torch.nn.Module):
    def forward(self, x):
        # The original implementation using ones_like, which might cause problem for input with dynamic axes in onnx.
        # return x * 0.5 * (torch.erf(x / 1.41421).to(dtype=x.dtype) + torch.ones_like(x).to(dtype=x.dtype))
        return x * 0.5 * (torch.erf(x / 1.41421).to(dtype=x.dtype) + 1.0)


class MegatronFastGelu(torch.nn.Module):
    def forward(self, x):
        return 0.5 * x * (1.0 + torch.tanh(0.7978845608028654 * x * (1.0 + 0.044715 * x * x)))


class TestGeluFusions(unittest.TestCase):
    def verify_node_count(self, bert_model, expected_node_count, test_name):
        for op_type, count in expected_node_count.items():
            if len(bert_model.get_nodes_by_op_type(op_type)) != count:
                print(f"Counters is not expected in test: {test_name}")
                for op, counter in expected_node_count.items():
                    print(f"{op}: {len(bert_model.get_nodes_by_op_type(op))} expected={counter}")
            self.assertEqual(len(bert_model.get_nodes_by_op_type(op_type)), count)

    @parameterized.expand(
        [
            (("huggingface", "Gelu", HuggingfaceGelu), True),
            (("huggingface", "FastGelu", HuggingfaceFastGelu), True),
            (("huggingface", "QuickGelu", HuggingfaceQuickGelu), True),
            (("huggingface", "FastGelu", HuggingfaceTorchGeluTanh), True),
            (("megatron", "Gelu", MegatronGelu), True),
            (("megatron", "FastGelu", MegatronFastGelu), True),
            (("huggingface", "Gelu", HuggingfaceGelu), False),
            (("huggingface", "FastGelu", HuggingfaceFastGelu), False),
            (("huggingface", "QuickGelu", HuggingfaceQuickGelu), False),
            (("huggingface", "FastGelu", HuggingfaceTorchGeluTanh), False),
            (("megatron", "Gelu", MegatronGelu), False),
            (("megatron", "FastGelu", MegatronFastGelu), False),
        ]
    )
    def test_fusions(self, test_case, dynamo):
        source, operator, model_class = test_case
        model = model_class()
        dummy_input = torch.ones(3, dtype=torch.float32)
        test_name = f"{operator}_{source}"
        onnx_path = f"{test_name}.onnx"
        torch.onnx.export(
            model,
            (dummy_input,),
            onnx_path,
            input_names=["input"],
            output_names=["output"],
            dynamo=dynamo,
            optimize=True,  # Only meaningful when dynamo is True
        )
        optimizer = optimize_model(onnx_path, "bert")
        # optimizer.save_model_to_file(f"{operator}_{source}_opt.onnx")
        os.remove(onnx_path)
        # Remove the associated .data file (dynamo)
        data_path = onnx_path + ".data"
        if os.path.exists(data_path):
            os.remove(data_path)
        expected_node_count = {operator: 1}

        self.verify_node_count(optimizer, expected_node_count, test_name)


if __name__ == "__main__":
    unittest.main()
