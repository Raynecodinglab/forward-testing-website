function formatPrice(price) {
    if (price === null || price === undefined) return '–';
    if (price >= 1000) return '$' + price.toFixed(2);
    if (price >= 1)    return '$' + price.toFixed(3);
    if (price >= 0.01) return '$' + price.toFixed(4);
    return '$' + price.toFixed(6);
}
