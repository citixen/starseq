DIM_FACTOR = 0.35   # shared brightness scale for anything in its 'dim' state


def dim_colour(col: tuple) -> tuple:
    return (int(col[0] * DIM_FACTOR),
            int(col[1] * DIM_FACTOR),
            int(col[2] * DIM_FACTOR))
