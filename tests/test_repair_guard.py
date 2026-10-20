import copy
import unittest
from easyread.repair_guard import retains_content


class RepairGuardTest(unittest.TestCase):
    def test_missing_block_field_or_table_cell_is_rejected(self):
        original = {'blocks': [{'id': 'p1', 'type': 'para', 'page': 1, 'zh': 'text'},
                               {'id': 't1', 'type': 'table', 'page': 1, 'rows': [['a', 'b']]}]}
        for mutation in ('block', 'field', 'cell', 'identity'):
            fixed = copy.deepcopy(original)
            if mutation == 'block': fixed['blocks'].pop()
            if mutation == 'field': fixed['blocks'][0]['zh'] = ''
            if mutation == 'cell': fixed['blocks'][1]['rows'][0].pop()
            if mutation == 'identity': fixed['blocks'][0]['id'] = 'other'
            with self.subTest(mutation=mutation):
                self.assertFalse(retains_content(original, fixed))
        fixed = copy.deepcopy(original)
        fixed['blocks'][0]['zh'] = 'fixed formula $x$'
        self.assertTrue(retains_content(original, fixed))


if __name__ == "__main__":
    unittest.main()
