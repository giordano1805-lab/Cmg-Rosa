/*
    Dark mode
 */
//Get the current theme value from local storage
const currentTheme = localStorage.getItem('theme')




//Check user preference at OS level
/*const prefersDarkScheme = window.matchMedia('(prefers-color-scheme: dark)')*/

//Reusable functions to switch to dark or light
function switchDark() {
    //Add a class to the body to enable the dark theme
    $('body').addClass('dark-theme')
    //Add the active class to this button
    $('.dark-mode-on').addClass('active')
    //Set the theme to 'dark' on the local storage value
    localStorage.setItem('theme', 'dark')
}

function switchLight() {
    //Remove the dark theme class from the body
    $('body').removeClass('dark-theme')
    //Add the active class to this button
    $('.dark-mode-off').addClass('active')
    //Set the theme to 'dark' on the local storage value
    localStorage.setItem('theme', 'light')
}



//check user preferences
function darkModeSwitch() {

    //determine if the clicked button is dark or light
    let themeValue = $(this).data('theme')

    //Remove classes from all switch buttons
    $('.dark-mode-switch').removeClass('active')

    //Switch theme according to the value
    if (themeValue === 'dark') {
        switchDark()
    } else {
        switchLight()
    }
}

//Theme switch button
$('.dark-mode-switch').on('click', darkModeSwitch)



/*
    Tabs
 */

//Define variables
var tab = $('.coes-tab')
var tabContent = $('.coes-tab--content')

//Event handler
function tabClickHandler(e) {

    //Get the data attribute of the clicked tab and store it
    let tabTarget = $(this).data('tab-target')

    //To execute only on THIS instance without affect other instances on the same page
    let closestParent = $(this).closest('.coes-tabs')

    //Execute only if there are 2 ore more tabs
    if (closestParent.find('.coes-tab').length >= 2) {
        //Remove classes from all tabs
        closestParent.find('.coes-tab').removeClass('coes-tab--active')

        //Remove classes from all content tabs
        closestParent.find('.coes-tab--content').removeClass('coes-tab--content-active')

        //Add a class to the clicked tab
        closestParent.find($(this)).addClass('coes-tab--active')

        //Display the content of the selected tab
        closestParent.find('#coes-tab-content-' + tabTarget).addClass('coes-tab--content-active')
    }
}

//Event
tab.on('click', tabClickHandler)

/*
    Slides
 */

//Picture slider -- homepage
$('.picture-slider').slick({
    infinite: true,
    arrows: false,
    dots: true,
    dotsClass: 'image-slider-dots'
})

//Shortcuts carousel -- homepage
$('.coes-shortcuts-carousel').slick({
    infinite: true,
    arrows: true,
    dots: false,
    slidesToShow: 8,
    responsive: [
        {
            breakpoint: 992,
            settings: {
                slidesToShow: 4,
            }
        },
        {
            breakpoint: 576,
            settings: {
                slidesToShow: 2,
            }
        },
    ]

})

//Shortcuts carousel -- homepage
$('.slider-prensa--container').slick({
    infinite: true,
    arrows: true,
    dots: false,
    slidesToShow: 2,
    slidesToScroll: 1,
    responsive: [
        {
            breakpoint: 992,
            settings: {
                slidesToShow: 1,
            }
        },
    ]
})

/*
    List - Thumbs view switch
*/


function InfoListViewSwitch() {
    $('.coes-views button').removeClass('active')
    $(this).addClass('active')

    if ($(this).hasClass('js-switch-list')) {
        $('.infolist').addClass('listed')
    } else {
        $('.infolist').removeClass('listed')
    }
}

$('.js-switch-list, .js-switch-thumbs').on('click', InfoListViewSwitch)


//Custom styles for selected item when using checkbox

function selectedCheckParent() {
    $(this).parent().toggleClass('selected')
}

$('.infolist-link').on('click', selectedCheckParent)

//Select all checkboxes: DEMO ONLY
function selectAllCheckboxes() {
    const $checkboxes = $('.infolist-item .coes-form-checkbox')
    $checkboxes.prop('checked', this.checked)
    $checkboxes.parent().toggleClass('selected')
}

$('#select-all').on('click', selectAllCheckboxes)


$(function () {

    //check theme from local storage and from the OS preferences
    (currentTheme === 'dark') ? switchDark() : switchLight()

    $("#txtSearch").on('keypress', function (e) {
        debugger;
        if (event.which == 13) {
            var texto = $('#txtSearch').val();

            if (texto.length >= 2) {
                document.location.href = siteRoot + 'search?k=' + texto;
            }
            else {
                alert("Escriba al menos 2 caracteres.");
            }
        }
    });

    $("#btnSearch").click(function (event) {
 
            var texto = $('#txtSearch').val();

            if (texto.length >= 2) {
                document.location.href = siteRoot + 'search?k=' + texto;
            }
            else {
                alert("Escriba al menos 2 caracteres.");
            }
        
    });
});

