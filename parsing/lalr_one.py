import parsing.lr_zero as lr_zero


class ParsingTable:
    def __init__(self, gr):
        # Taken from the grammar directly
        self.terminals = [] # gr.end_of_input() will be added to 'terminals'
        self.nonterms = []  # gr.start() will be removed from 'nonterms'

        # Taken from the cardinality of the LALR(1) canonical collection
        self.n_states = 0

        # goto will be a list of dictionaries in order to easy its usage:
        #   goto[state_id][nonterminal]
        # Each dictionary will map a non-terminal to an int: the index of the next state.
        # If for a given non-terminal there's no transition, it will map to None instead.
        #
        # action will be a list of dictionaries in order to easy its usage:
        #   action[state_id][terminal]
        # Each dictionary will map a terminal to a set of "table entries".
        # The type of a table entry varies according to the kind of entry:
        #   a "shift #state_id" entry           is a 2-tuple ('shift', state_id)
        #   a "reduce #production_index" entry  is a 2-tuple ('reduce', production_index)
        #   an "accept" entry                   is just a 2-tuple ('accept', '')
        #   an "error" entry                    is represented by an empty set
        #
        # See Dragonbook, page 265, "Canonical LR(1) parsing tables" for reference.

        self.goto = []
        self.action = []

        self.__setup_from_grammar(gr)

    def __setup_from_grammar(self, gr):
        self.terminals = gr.terminals + [gr.end_of_input()]
        self.nonterms = gr.nonterms[1:]  # Ignore the first non-terminal, Grammar.start()

        ccol = tuple(get_canonical_collection(gr))
        self.n_states = len(ccol)

        ccol_core = tuple(self.__drop_lalr_one_itemset_lookaheads(x) for x in ccol)
        id_from_core = {ccol_core[i]: i for i in range(len(ccol))}

        def id_from_lr_one_state(itemset):
            return id_from_core[self.__drop_lalr_one_itemset_lookaheads(itemset)]

        self.goto = [{x: None for x in self.nonterms} for i in range(self.n_states)]
        self.action = [{x: set() for x in self.terminals} for i in range(self.n_states)]

        for state_id in range(self.n_states):
            for item, next_symbol in ccol[state_id]:
                prod_index, dot = item
                pname, pbody = gr.productions[prod_index]

                if dot < len(pbody):
                    terminal = pbody[dot]
                    if not isinstance(terminal, str):
                        continue

                    next_state = goto(gr, ccol[state_id], terminal)
                    if len(next_state) == 0:
                        continue
                    next_state_id = id_from_lr_one_state(next_state)

                    self.action[state_id][terminal].add(('shift', next_state_id))
                else:
                    if prod_index == 0:
                        # We are dealing with an item of the artificial starting symbol
                        assert(next_symbol == gr.end_of_input())
                        self.action[state_id][gr.end_of_input()].add(('accept', ''))
                    else:
                        # We are dealing with a regular non-terminal
                        self.action[state_id][next_symbol].add(('reduce', prod_index))

            for nt in self.nonterms:
                next_state = goto(gr, ccol[state_id], nt)
                if len(next_state) == 0:
                    continue

                next_state_id = id_from_lr_one_state(next_state)
                self.goto[state_id][nt] = next_state_id

    @staticmethod
    def __drop_lalr_one_itemset_lookaheads(itemset):
        return frozenset((x[0], x[1]) for x, y in itemset)

    def stringify(self):
        result = 'PARSING TABLE\n'
        for state_id in range(self.n_states):
            result += ('\n' if state_id > 0 else '')
            result += 'State #%d\n' % state_id

            for terminal, entries in self.action[state_id].items():
                if len(entries) == 0:
                    continue
                result += '\tfor terminal %s: ' % terminal
                result += ','.join('%s %s' % (kind, str(arg)) for kind, arg in entries)
                result += '\n'

            for nt, next_state_id in self.goto[state_id].items():
                if next_state_id is None:
                    continue
                result += '\tfor non-terminal %s: go to state %d\n' % (repr(nt), next_state_id)

        return result


class LrZeroItemTableEntry:
    def __init__(self):
        self.propagates_to = set()
        self.lookaheads = set()

    def __repr__(self):
        pattern = '{ propagatesTo: %s, lookaheads: %s }'
        return pattern % (repr(self.propagates_to), repr(self.lookaheads))


def get_canonical_collection(gr):
    # See Dragonbook, page 272, "Algorithm 4.63"

    # STEP 1
    # ======
    dfa = lr_zero.get_automaton(gr)
    kstates = [lr_zero.kernels(st) for st in dfa.states]
    n_states = len(kstates)

    # STEPS 2, 3
    # ==========
    table = [{item: LrZeroItemTableEntry() for item in kstates[i]} for i in range(n_states)]
    table[0][(0, 0)].lookaheads.add(gr.end_of_input())

    for i_state_id in range(n_states):
        state_symbols = [x[1] for x, y in dfa.goto.items() if x[0] == i_state_id]

        for i_item in kstates[i_state_id]:
            closure_set = closure(gr, [(i_item, gr.free_symbol())])

            for sym in state_symbols:
                j_state_id = dfa.goto[(i_state_id, sym)]

                # For each item in closure_set whose . (dot) points to a symbol equal to 'sym'
                # i.e. a production expecting to see 'sym' next
                for ((prod_index, dot), next_symbol) in closure_set:
                    pname, pbody = gr.productions[prod_index]
                    if dot == len(pbody) or pbody[dot] != sym:
                        continue

                    j_item = (prod_index, dot + 1)
                    if next_symbol == gr.free_symbol():
                        table[i_state_id][i_item].propagates_to.add((j_state_id, j_item))
                    else:
                        table[j_state_id][j_item].lookaheads.add(next_symbol)

    # STEP 4
    # ======
    repeat = True
    while repeat:
        repeat = False
        # For every item set, kernel item
        for i_state_id in range(len(table)):
            for i_item, i_cell in table[i_state_id].items():
                # For every kernel item i_item's lookaheads propagate to
                for j_state_id, j_item in i_cell.propagates_to:
                    # Do propagate the lookaheads
                    j_cell = table[j_state_id][j_item]
                    j_cell_lookaheads_len = len(j_cell.lookaheads)
                    j_cell.lookaheads.update(i_cell.lookaheads)
                    # Check if they changed, so we can decide whether to iterate again
                    if j_cell_lookaheads_len < len(j_cell.lookaheads):
                        repeat = True

    # Build the collection
    # ====================
    result = [set() for i in range(n_states)]
    for i_state_id in range(n_states):
        # Add kernel items
        for i_item, i_cell in table[i_state_id].items():
            for sym in i_cell.lookaheads:
                item_set = (i_item, sym)
                result[i_state_id].add(item_set)
        # Add non-kernel kernel items
        result[i_state_id] = closure(gr, result[i_state_id])

    return result


def closure(gr, item_set):
    result = set(item_set)
    current = item_set

    while len(current) > 0:
        new_elements = []

        for ((prod_index, dot), lookahead) in current:
            pname, pbody = gr.productions[prod_index]
            if dot == len(pbody) or pbody[dot] not in gr.nonterms:
                continue

            nt = pbody[dot]
            nt_offset = gr.nonterm_offset[nt]
            following_symbols = pbody[dot+1:] + [lookahead]
            following_terminals = gr.first_set(following_symbols) - {None}

            for idx in range(len(nt.productions)):
                for term in following_terminals:
                    new_item_set = ((nt_offset + idx, 0), term)
                    if new_item_set not in result:
                        result.add(new_item_set)
                        new_elements += [new_item_set]

        current = new_elements

    return frozenset(result)


def goto(gr, item_set, inp):
    result_set = set()
    for (item, lookahead) in item_set:
        prod_id, dot = item
        pname, pbody = gr.productions[prod_id]
        if dot == len(pbody) or pbody[dot] != inp:
            continue

        new_item = ((prod_id, dot + 1), lookahead)
        result_set.add(new_item)

    result_set = closure(gr, result_set)
    return result_set
