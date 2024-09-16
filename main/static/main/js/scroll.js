function scrollToElement(tableId, elementPrefix, elementId) {
    let $tbody = $(`#${tableId} tbody`);
    let $tr = $(`#${elementPrefix}-${elementId}`);

    if ($tbody.length && $tr.length) {
        // Get bounding rectangles
        let tbodyRect = $tbody[0].getBoundingClientRect();
        let trRect = $tr[0].getBoundingClientRect();

        // Calculate scroll positions
        let offsetTop = trRect.top - tbodyRect.top + $tbody.scrollTop();
        let offsetLeft = trRect.left - tbodyRect.left + $tbody.scrollLeft();

        // Scroll vertically and horizontally to center the row
        let scrollTopValue = offsetTop - ($tbody.height() / 2 - $tr.outerHeight() / 2);
        let scrollLeftValue = offsetLeft - ($tbody.width() / 2 - $tr.outerWidth() / 2);
        $tbody.scrollTop(scrollTopValue);
        $tbody.scrollLeft(scrollLeftValue);

        // Remove bold styling from any previously bolded row in this table
        $tbody.find('tr').css('font-weight', 'normal');

        // Apply bold styling to the current row
        $tr.css('font-weight', 'bold');

        console.log(`Scrolled to and applied bolding for ${elementPrefix}-${elementId}`);
    }
}
