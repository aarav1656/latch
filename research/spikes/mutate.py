def evaluate(total, done):
    unfinished = total - done
    finished = done
    if total == 2 and done == 1:
        if unfinished == finished:
            print(f"SYMMETRIC {finished} {unfinished} PASS")
    elif total == 3 and done == 1:
        if unfinished != finished:
            print(f"ASYMMETRIC {finished} {unfinished} FAIL")


if __name__ == "__main__":
    evaluate(2, 1)
    evaluate(3, 1)
