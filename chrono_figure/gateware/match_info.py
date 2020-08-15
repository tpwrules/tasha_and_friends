# constants related to the matchers

# all the types of matches
MATCH_TYPE_NONE = 0
MATCH_TYPE_RESET = 1
MATCH_TYPE_NMI = 2
MATCH_TYPE_WAIT_START = 3
MATCH_TYPE_WAIT_END = 4

MATCH_TYPE_BITS = 6 # number of bits required to represent the above (max 8)

NUM_MATCHERS = 32 # how many match engines are there?
MATCHER_BITS = 5 # number of bits required to represent the above (max 8)
