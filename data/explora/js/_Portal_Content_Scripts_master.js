$(function () {

    $('.top-option-item > li > a').mouseover(function () {
        var item = $(this).attr('data-tooltip');
        var pos= ($(this).parent().parent().children().index($(this).parent()));
        $(this).append("<div class='top-tooltip' style='margin-left:" + (33*pos - 30)   + "px'>" + item + "</div>");
    });

    $('.top-option-item > li > a').mouseout(function () {
       $('.top-tooltip').remove();
    });

    $("#txtSearch").keypress(function (event) {
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
});

$(document).ajaxStart(function () {
    $('#loading').bPopup({
        fadeSpeed: 'fast',
        opacity: 0.4,
        followSpeed: 500,
        modalColor: '#fff'
    });
});

$(document).ajaxStop(function () {
    $('#loading').bPopup().close();
});


openCalendario = function () {
    $.ajax({
        type: 'POST',
        url: siteRoot + 'home/calendario',
        success: function (evt) {
            $('#contenidoCalendario').html(evt);
            setTimeout(function () {
                $('#popupCalendario').bPopup({
                    autoClose: false
                });
                $("#calendar").fullCalendar('render');
            }, 100);
        },
        error: function () {
            //mostrarMensaje('mensaje', 'error', 'Se ha producido un error.');
        }
    });

}

closeAvisoCalendario = function () {
    $('#avisoCalendario').hide();

    //$.ajax({
    //    type: 'POST',
    //    url: siteRoot + 'home/closeavisocalendario',
    //    dateType: 'json',
    //    success: function (result)
    //    {

    //    },
    //    error: function () {
    //    }
    //});
}