"""Test JSON parser behavior with different inputs to isolate the precise cause of JSON parsing errors.

This script helps understand how Python's json.loads() behaves with different inputs, focusing
on the specific 'Unexpected non-whitespace character after JSON at position 4' error.
"""

import json
import sys
import os
import unittest
import re

class JSONParserTest(unittest.TestCase):
    """Test class for examining JSON parser behavior."""
    
    def test_valid_json(self):
        """Test parsing of valid JSON objects."""
        valid_inputs = [
            '{}',
            '{"key": "value"}',
            '{"a": 1, "b": 2}',
            '{"escaped": "quote \\"inside\\""}',
            '{"unicode": "한글 테스트"}',
            ' \n\t{"whitespace": "before and after"} \n\r'
        ]
        
        for i, input_str in enumerate(valid_inputs):
            try:
                result = json.loads(input_str)
                print(f"✓ Valid JSON #{i+1} parsed successfully: {result}")
            except json.JSONDecodeError as e:
                self.fail(f"Failed to parse valid JSON #{i+1}: {input_str}\nError: {e}")
    
    def test_invalid_json_common_errors(self):
        """Test parsing of commonly invalid JSON that triggers parsing errors."""
        invalid_inputs = [
            ('{}abc', "Extra characters after JSON"),
            ('{key: "value"}', "Missing quotes around key"),
            ('{"key": value}', "Missing quotes around value"),
            ('{"key": "value"', "Missing closing brace"),
            ('{"key": "value",}', "Trailing comma"),
            ('{"key": "value} abc', "Unterminated string"),
            ('{"jsonrpc":"2.0","id":1,method:"list"}', "Mixed quoting styles"),
        ]
        
        for i, (input_str, desc) in enumerate(invalid_inputs):
            try:
                result = json.loads(input_str)
                print(f"✗ Invalid JSON #{i+1} ({desc}) parsed without error: {result}")
                self.fail(f"Should have failed to parse: {input_str}")
            except json.JSONDecodeError as e:
                print(f"✓ Expected error for invalid JSON #{i+1} ({desc}): {e}")
                print(f"  Position: {e.pos}, Line: {e.lineno}, Column: {e.colno}")
                
                # Print a visual indicator of error position
                if hasattr(e, 'doc') and e.doc:
                    context_start = max(0, e.pos - 10)
                    context_end = min(len(e.doc), e.pos + 10)
                    print(f"  Context: '{e.doc[context_start:context_end]}'")
                    pos_indicator = ' ' * (min(10, e.pos) - context_start) + '^'
                    print(f"           {pos_indicator}")
    
    def test_position_4_error_cases(self):
        """Test specifically for cases that produce the position 4 error."""
        pos4_inputs = [
            '{}abc',  # Empty object followed by non-whitespace
            '{"a":1}xyz',  # Valid object followed by non-whitespace
            '[]abc',  # Empty array followed by non-whitespace
            '{"key": "val"}{"another":"obj"}',  # Multiple objects without separator
        ]
        
        for i, input_str in enumerate(pos4_inputs):
            try:
                result = json.loads(input_str)
                print(f"✗ Position 4 test #{i+1} parsed without error: {result}")
                self.fail(f"Should have failed to parse: {input_str}")
            except json.JSONDecodeError as e:
                print(f"✓ Error for position 4 test #{i+1}: {e}")
                # Check if this is the position 4 error we're looking for
                if 'at position 4' in str(e) or e.pos == 4:
                    print(f"  Found position 4 error!")
                print(f"  Position: {e.pos}, Line: {e.lineno}, Column: {e.colno}")
                # Visual indicator
                if hasattr(e, 'doc') and e.doc:
                    context_start = max(0, e.pos - 10)
                    context_end = min(len(e.doc), e.pos + 10)
                    print(f"  Context: '{e.doc[context_start:context_end]}'")
                    pos_indicator = ' ' * (min(10, e.pos) - context_start) + '^'
                    print(f"           {pos_indicator}")
    
    def test_real_world_error_simulation(self):
        """Simulate the real-world error cases reported from logs."""
        # These patterns attempt to recreate the exact error seen in the logs
        error_patterns = [
            # Test cases designed to trigger the specific position 4 error
            '{}abc',  # Basic case - empty object followed by text
            '{"jsonrpc":"2.0"}{"id":1}',  # Two objects without separator 
            '{"complete":true}{"partial":',  # Complete object followed by incomplete one
            '{}{"id":1,method:"test"}',  # Empty object followed by invalid object
        ]
        
        for i, pattern in enumerate(error_patterns):
            try:
                result = json.loads(pattern)
                print(f"✗ Real-world pattern #{i+1} parsed without error: {result}")
                self.fail(f"Should have failed to parse: {pattern}")
            except json.JSONDecodeError as e:
                print(f"✓ Error for real-world pattern #{i+1}: {e}")
                print(f"  Position: {e.pos}, Line: {e.lineno}, Column: {e.colno}")
                
                # Check for position 4 error specifically
                match = re.search(r'position (\d+)', str(e))
                position = int(match.group(1)) if match else -1
                
                if position == 4:
                    print(f"  ★ Found our target 'position 4' error!")
                
                # Visual indicator of error position
                if hasattr(e, 'doc') and e.doc:
                    context_start = max(0, e.pos - 10)
                    context_end = min(len(e.doc), e.pos + 10)
                    print(f"  Context: '{e.doc[context_start:context_end]}'")
                    pos_indicator = ' ' * (min(10, e.pos) - context_start) + '^'
                    print(f"           {pos_indicator}")
    
    def test_json_message_concatenation(self):
        """Test if the error happens when multiple JSON messages are concatenated without proper delimiters."""
        inputs = [
            # Multiple JSON messages with various delimiters
            ('{"msg1":true}{"msg2":false}', "No delimiter"),
            ('{"msg1":true}\n{"msg2":false}', "Newline delimiter"),
            ('{"msg1":true} \n\n {"msg2":false}', "Whitespace + newline delimiter"),
            ('{"msg1":true}     {"msg2":false}', "Multiple spaces"),
        ]
        
        for i, (input_str, desc) in enumerate(inputs):
            try:
                result = json.loads(input_str)
                print(f"✗ Concatenation test #{i+1} ({desc}) parsed without error: {result}")
                self.fail(f"Should have failed to parse: {input_str}")
            except json.JSONDecodeError as e:
                print(f"✓ Error for concatenation test #{i+1} ({desc}): {e}")
                
                # For successful cases, show detailed information about where parsing stopped
                last_valid_json = input_str[:e.pos]
                try:
                    parsed = json.loads(last_valid_json)
                    print(f"  Last valid JSON: {parsed}")
                    print(f"  Parser stopped at: '{input_str[e.pos:e.pos+10]}...'")
                except:
                    print(f"  Could not parse even the part before error position")

if __name__ == "__main__":
    print("\n=== JSON Parser Behavior Tests ===\n")
    unittest.main(argv=['first-arg-is-ignored'], exit=False) 