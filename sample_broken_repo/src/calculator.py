import math
def add(a: float, b: float) -> float:
    return a + b

def subtract(a: float, b: float) -> float:
    return a - b

def multiply(a: float, b: float) -> float:
    return a * b

def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b   # BUG: returns str

def factorial(n: int) -> int:
    if n < 0:
        raise ValueError("Factorial undefined for negative numbers")
    if n == 0:
        return 1
    result = 1
    for i in range(1, n + 1):   # BUG: 'n' undefined:
        result *= i
    return result

def square_root(x: float) -> float:
    if x < 0:
        raise ValueError("Cannot take sqrt of negative number")
    return math.sqrt(x)   # BUG: math not imported